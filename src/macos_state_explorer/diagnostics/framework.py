from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.rules import DiagnosticRule, RuleEngine, RuleMatch


@dataclass(frozen=True)
class DiagnosticEvidence:
    id: str
    title: str
    detail: str
    source: str
    present: bool = True
    confidence: float = 0.8
    provenance: list[str] = field(default_factory=list)


class RepairSafety(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    INTERACTIVE = "interactive"


class RepairStatus(str, Enum):
    DRY_RUN = "DRY_RUN"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NOT_FOUND = "NOT_FOUND"


def _repair_command_failure_message(exit_code: int, stderr: str) -> str:
    normalized = stderr.lower()
    if "option has been removed" in normalized:
        return (
            "Command failed because this macOS version removed an lsregister option; "
            f"do not retry the obsolete option set. Exit code: {exit_code}."
        )
    if "illegal option" in normalized or "unknown option" in normalized or "invalid option" in normalized:
        return (
            "Command failed because this macOS version does not support one of the requested options; "
            "use the manual reinstall or trace fallback branch before retrying automated refresh. "
            f"Exit code: {exit_code}."
        )
    return f"Command failed with exit code {exit_code}."


class RepairPlanStatus(str, Enum):
    DRY_RUN = "DRY_RUN"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RepairVerification:
    status: str
    branch_id: str
    observed_result: str
    evidence_ids: list[str] = field(default_factory=list)
    continues_workflow: bool = False
    transition: str | None = None
    next_step: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "branch_id": self.branch_id,
            "observed_result": self.observed_result,
            "evidence_ids": list(self.evidence_ids),
            "continues_workflow": self.continues_workflow,
            "transition": self.transition,
            "next_step": self.next_step,
        }


@dataclass(frozen=True)
class RepairPrecondition:
    id: str
    title: str
    satisfied: bool
    detail: str

    def to_json_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "satisfied": self.satisfied, "detail": self.detail}


@dataclass(frozen=True)
class RepairRollback:
    available: bool
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {"available": self.available, "description": self.description, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class RepairCommand:
    argv: tuple[str, ...]
    description: str

    def to_json_dict(self, exit_code: int | None = None) -> dict[str, Any]:
        return {"argv": list(self.argv), "description": self.description, "exit_code": exit_code}


CommandRunner = Callable[[list[str]], tuple[int, str, str]]


@dataclass(frozen=True)
class RepairPreflightResult:
    supported: bool
    message: str
    errors: tuple[str, ...] = ()
    executed_commands: tuple[dict[str, Any], ...] = ()


RepairPreflight = Callable[[CommandRunner], RepairPreflightResult]


@dataclass(frozen=True)
class RepairResult:
    module: str
    command_name: str
    action_id: str
    candidate_id: str | None
    status: RepairStatus
    dry_run: bool
    safety_classification: RepairSafety | str
    why_safe: str
    preconditions: tuple[RepairPrecondition, ...] = ()
    rollback: RepairRollback = field(default_factory=lambda: RepairRollback(False, "No rollback metadata provided."))
    executed_commands: tuple[dict[str, Any], ...] = ()
    message: str = ""
    files_touched: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    audit_log: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        safety = self.safety_classification.value if isinstance(self.safety_classification, RepairSafety) else self.safety_classification
        return {
            "command": f"repair {self.command_name}",
            "module": self.module,
            "action_id": self.action_id,
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "dry_run": self.dry_run,
            "safety_classification": safety,
            "why_safe": self.why_safe,
            "preconditions": [precondition.to_json_dict() for precondition in self.preconditions],
            "rollback": self.rollback.to_json_dict(),
            "executed_commands": list(self.executed_commands),
            "message": self.message,
            "files_touched": list(self.files_touched),
            "errors": list(self.errors),
            "audit_log": self.audit_log,
        }

    def render_text(self) -> str:
        lines = [
            "Repair action",
            f"- Module: {self.module}",
            f"- Action: {self.action_id}",
            f"- Candidate: {self.candidate_id or 'none'}",
            f"- Status: {self.status.value}",
            f"- Dry run: {'yes' if self.dry_run else 'no'}",
            f"- Safety: {self.safety_classification.value if isinstance(self.safety_classification, RepairSafety) else self.safety_classification}",
            f"- Why safe: {self.why_safe}",
            "",
            "Preconditions",
        ]
        if self.preconditions:
            for precondition in self.preconditions:
                state = "ok" if precondition.satisfied else "blocked"
                lines.append(f"- {precondition.id} [{state}] {precondition.title}: {precondition.detail}")
        else:
            lines.append("- none")
        lines.extend(["", "Rollback", f"- {self.rollback.description}", "", "Files touched"])
        if self.files_touched:
            for path in self.files_touched:
                lines.append(f"- {path}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("Commands")
        if self.executed_commands:
            for command in self.executed_commands:
                rendered = " ".join(command["argv"])
                exit_code = command.get("exit_code")
                suffix = "not run" if exit_code is None else f"exit {exit_code}"
                lines.append(f"- {rendered} ({suffix})")
        else:
            lines.append("- none")
        if self.errors:
            lines.extend(["", "Errors"])
            for error in self.errors:
                lines.append(f"- {error}")
        if self.audit_log:
            lines.extend(["", "Audit log", f"- {self.audit_log}"])
        if self.message:
            lines.extend(["", "Message", f"- {self.message}"])
        return "\n".join(lines)


@dataclass(frozen=True)
class RepairAction:
    id: str
    title: str
    description: str
    safety: RepairSafety | str
    why_safe: str
    commands: tuple[RepairCommand, ...] = ()
    preconditions: tuple[RepairPrecondition, ...] = ()
    rollback: RepairRollback = field(default_factory=lambda: RepairRollback(False, "No automated rollback is available."))
    files_touched: tuple[str, ...] = ()
    runner: CommandRunner | None = None
    preflight: RepairPreflight | None = None

    @staticmethod
    def candidate(
        *,
        id: str,
        title: str,
        risk: str,
        manual_action: str,
        expected_result: str,
        verification_command: str,
        fallback_branch: str,
        evidence_ids: list[str] | None = None,
        action_id: str | None = None,
    ) -> "RepairCandidate":
        return RepairCandidate(
            id=id,
            title=title,
            risk=risk,
            manual_action=manual_action,
            expected_result=expected_result,
            verification_command=verification_command,
            fallback_branch=fallback_branch,
            evidence_ids=list(evidence_ids or []),
            action_id=action_id,
        )

    def run(
        self,
        *,
        module: str = "",
        command_name: str = "",
        candidate_id: str | None = None,
        dry_run: bool,
    ) -> RepairResult:
        command_records = tuple(command.to_json_dict() for command in self.commands)
        if dry_run:
            return RepairResult(
                module=module,
                command_name=command_name or module,
                action_id=self.id,
                candidate_id=candidate_id,
                status=RepairStatus.DRY_RUN,
                dry_run=True,
                safety_classification=self.safety,
                why_safe=self.why_safe,
                preconditions=self.preconditions,
                rollback=self.rollback,
                executed_commands=command_records,
                message="Dry run only; no commands were executed.",
                files_touched=self.files_touched,
            )
        failed_preconditions = [precondition for precondition in self.preconditions if not precondition.satisfied]
        if failed_preconditions:
            return RepairResult(
                module=module,
                command_name=command_name or module,
                action_id=self.id,
                candidate_id=candidate_id,
                status=RepairStatus.BLOCKED,
                dry_run=False,
                safety_classification=self.safety,
                why_safe=self.why_safe,
                preconditions=self.preconditions,
                rollback=self.rollback,
                executed_commands=command_records,
                message="One or more preconditions failed; no commands were executed.",
                files_touched=self.files_touched,
                errors=tuple(f"Precondition failed: {precondition.id}" for precondition in failed_preconditions),
            )
        runner = self.runner or default_command_runner
        executed: list[dict[str, Any]] = []
        if self.preflight is not None:
            preflight_result = self.preflight(runner)
            executed.extend(preflight_result.executed_commands)
            if not preflight_result.supported:
                return RepairResult(
                    module=module,
                    command_name=command_name or module,
                    action_id=self.id,
                    candidate_id=candidate_id,
                    status=RepairStatus.FAILED,
                    dry_run=False,
                    safety_classification=self.safety,
                    why_safe=self.why_safe,
                    preconditions=self.preconditions,
                    rollback=self.rollback,
                    executed_commands=tuple(executed),
                    message=preflight_result.message,
                    files_touched=self.files_touched,
                    errors=preflight_result.errors or (preflight_result.message,),
                )
        for command in self.commands:
            exit_code, stdout, stderr = runner(list(command.argv))
            record = command.to_json_dict(exit_code=exit_code)
            if stdout:
                record["stdout"] = stdout
            if stderr:
                record["stderr"] = stderr
            executed.append(record)
            if exit_code != 0:
                message = _repair_command_failure_message(exit_code, stderr)
                return RepairResult(
                    module=module,
                    command_name=command_name or module,
                    action_id=self.id,
                    candidate_id=candidate_id,
                    status=RepairStatus.FAILED,
                    dry_run=False,
                    safety_classification=self.safety,
                    why_safe=self.why_safe,
                    preconditions=self.preconditions,
                    rollback=self.rollback,
                    executed_commands=tuple(executed),
                    message=message,
                    files_touched=self.files_touched,
                    errors=(stderr or message,),
                )
        return RepairResult(
            module=module,
            command_name=command_name or module,
            action_id=self.id,
            candidate_id=candidate_id,
            status=RepairStatus.SUCCESS,
            dry_run=False,
            safety_classification=self.safety,
            why_safe=self.why_safe,
            preconditions=self.preconditions,
            rollback=self.rollback,
            executed_commands=tuple(executed),
            message="Repair action completed.",
            files_touched=self.files_touched,
        )


def default_command_runner(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout, completed.stderr


@dataclass(frozen=True)
class RepairCandidate:
    id: str
    title: str
    risk: str
    manual_action: str
    expected_result: str
    verification_command: str
    fallback_branch: str
    evidence_ids: list[str] = field(default_factory=list)
    action_id: str | None = None


@dataclass(frozen=True)
class RepairStep:
    index: int
    candidate: RepairCandidate
    action: RepairAction | None
    skipped_reason: str | None = None

    @property
    def candidate_id(self) -> str:
        return self.candidate.id

    @property
    def action_id(self) -> str | None:
        return self.action.id if self.action else self.candidate.action_id

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "candidate_id": self.candidate.id,
            "candidate": repair_candidate_to_json(self.candidate),
            "action_id": self.action_id,
            "safety_classification": _repair_safety_value(self.action.safety) if self.action else None,
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True)
class RepairPlan:
    module: str
    command_name: str
    steps: tuple[RepairStep, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": f"repair {self.command_name}",
            "module": self.module,
            "steps": [step.to_json_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class RepairStepResult:
    index: int
    candidate_id: str
    action_id: str | None
    status: str
    repair_result: RepairResult | None = None
    verification: RepairVerification | None = None
    message: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "candidate_id": self.candidate_id,
            "action_id": self.action_id,
            "status": self.status,
            "repair_result": self.repair_result.to_json_dict() if self.repair_result else None,
            "verification": self.verification.to_json_dict() if self.verification else None,
            "message": self.message,
        }


@dataclass(frozen=True)
class RepairPlanResult:
    module: str
    command_name: str
    status: RepairPlanStatus
    dry_run: bool
    confirmed: bool
    plan: RepairPlan
    step_results: tuple[RepairStepResult, ...]
    message: str = ""
    audit_log: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": f"repair {self.command_name}",
            "module": self.module,
            "status": self.status.value,
            "dry_run": self.dry_run,
            "confirmed": self.confirmed,
            "plan": self.plan.to_json_dict(),
            "step_results": [step.to_json_dict() for step in self.step_results],
            "message": self.message,
            "audit_log": self.audit_log,
        }

    def render_text(self) -> str:
        lines = [
            "Repair plan",
            f"- Module: {self.module}",
            f"- Status: {self.status.value}",
            f"- Dry run: {'yes' if self.dry_run else 'no'}",
            f"- Confirmed: {'yes' if self.confirmed else 'no'}",
            "",
            "Steps",
        ]
        for step_result in self.step_results:
            lines.append(
                f"{step_result.index}. {step_result.candidate_id}"
                f" ({step_result.action_id or 'manual-only'}) — {step_result.status}"
            )
            if step_result.verification:
                lines.append(
                    f"   Verification: {step_result.verification.status} — {step_result.verification.observed_result}"
                )
            if step_result.message:
                lines.append(f"   {step_result.message}")
        if self.audit_log:
            lines.extend(["", "Audit log", f"- {self.audit_log}"])
        if self.message:
            lines.extend(["", "Message", f"- {self.message}"])
        return "\n".join(lines)


@dataclass(frozen=True)
class DiagnosticSolution:
    command_name: str
    diagnosis: str
    evidence: list[DiagnosticEvidence]
    repair_plan: list[RepairCandidate]
    rule_matches: list[RuleMatch] = field(default_factory=list)
    supporting_commands: tuple[str, ...] = ()
    remediation_plan_summary: dict[str, Any] | None = None
    launchservices_outcome_summary: dict[str, Any] | None = None

    def render_text(self) -> str:
        primary = self.repair_plan[0]
        lines = [
            "Current diagnosis",
            f"- {self.diagnosis}",
            "",
            "Evidence",
        ]
        for evidence in self.evidence:
            state = "present" if evidence.present else "absent"
            provenance = f"; provenance {', '.join(evidence.provenance)}" if evidence.provenance else ""
            lines.append(
                f"- {evidence.id} [{state}, confidence {evidence.confidence:.0%}{provenance}] "
                f"{evidence.title}: {evidence.detail}"
            )

        if self.remediation_plan_summary:
            from macos_state_explorer.launchservices.remediation_plan import render_remediation_plan_summary

            lines.extend(["", render_remediation_plan_summary(self.remediation_plan_summary)])
        if self.launchservices_outcome_summary:
            from macos_state_explorer.launchservices.outcome import render_outcome_summary

            lines.extend(["", render_outcome_summary(self.launchservices_outcome_summary)])

        if self.rule_matches:
            lines.extend(["", "Rule explanation"])
            for match in self.rule_matches:
                lines.append(f"- {match.rule_id} → {match.diagnosis_id}")
                lines.append(f"  Matched evidence: {', '.join(sorted(match.evidence_ids))}")
                if match.matched_optional_evidence:
                    lines.append(f"  Optional evidence: {', '.join(match.matched_optional_evidence)}")
                lines.append(f"  Confidence contribution: {match.confidence_contribution:.0%}")
                lines.append(f"  Explanation: {match.explanation}")

        lines.extend(
            [
                "",
                "Repair candidate",
                f"- {primary.title}",
                f"- Manual only: {primary.manual_action}",
                f"- Evidence: {', '.join(primary.evidence_ids)}",
                "",
                "Risk",
                f"- {primary.risk}",
                "",
                "Expected result",
                f"- {primary.expected_result}",
                "",
                "Verification command",
                f"- {primary.verification_command}",
                "",
                "Fallback branch",
                f"- {primary.fallback_branch}",
                "",
                "Branch order",
            ]
        )
        for index, candidate in enumerate(self.repair_plan, start=1):
            lines.append(
                f"{index}. {candidate.id} — {candidate.title} "
                f"(Evidence: {', '.join(candidate.evidence_ids)})"
            )
        if self.supporting_commands:
            lines.extend(["", "Supporting read-only commands"])
            for command in self.supporting_commands:
                lines.append(f"- {command}")
        return "\n".join(lines)

    def to_json_dict(self) -> dict[str, Any]:
        payload = {
            "command": f"solve {self.command_name}",
            "diagnosis": self.diagnosis,
            "evidence": [evidence_to_json(item) for item in sorted(self.evidence, key=lambda item: item.id)],
            "matched_rules": [rule_match_to_json(match) for match in self.rule_matches],
            "repair_candidates": [repair_candidate_to_json(candidate) for candidate in self.repair_plan],
            "next_action": repair_candidate_to_json(self.repair_plan[0]),
        }
        if self.remediation_plan_summary is not None:
            payload["remediation_plan_summary"] = self.remediation_plan_summary
        if self.launchservices_outcome_summary is not None:
            payload["launchservices_outcome_summary"] = self.launchservices_outcome_summary
        return payload


EvidenceProvider = Callable[[Snapshot, dict[str, Any] | None], Sequence[DiagnosticEvidence]]
RepairCandidateFactory = Callable[[Sequence[DiagnosticEvidence], dict[str, Any] | None], dict[str, RepairCandidate]]
RepairActionFactory = Callable[
    [Sequence[DiagnosticEvidence], dict[str, RepairCandidate], dict[str, Any] | None],
    dict[str, RepairAction],
]
RepairVerifier = Callable[[Snapshot, RepairCandidate, dict[str, Any] | None], RepairVerification]
SnapshotProvider = Callable[[], Snapshot]
DiagnosisBuilder = Callable[
    [Sequence[DiagnosticEvidence], Sequence[RuleMatch], Sequence[RepairCandidate], dict[str, Any] | None],
    str,
]


def no_repair_actions(
    evidence: Sequence[DiagnosticEvidence],
    candidates: dict[str, RepairCandidate],
    context: dict[str, Any] | None = None,
) -> dict[str, RepairAction]:
    return {}


@dataclass(frozen=True)
class DiagnosticModule:
    id: str
    command_name: str
    evidence_provider: EvidenceProvider
    rules: Sequence[DiagnosticRule]
    repair_candidates: RepairCandidateFactory
    diagnosis_builder: DiagnosisBuilder
    repair_actions: RepairActionFactory = no_repair_actions
    repair_verifier: RepairVerifier | None = None
    fallback_repair_order: tuple[str, ...] = ()
    supporting_commands: tuple[str, ...] = ()


class DiagnosticRegistry:
    def __init__(self, modules: Sequence[DiagnosticModule] = ()) -> None:
        self._modules: dict[str, DiagnosticModule] = {}
        for module in modules:
            self.register(module)

    def register(self, module: DiagnosticModule) -> None:
        if module.id in self._modules:
            raise ValueError(f"Diagnostic module {module.id!r} is already registered")
        self._modules[module.id] = module

    def get(self, module_id: str) -> DiagnosticModule:
        if module_id not in self._modules:
            raise KeyError(module_id)
        return self._modules[module_id]

    def modules(self) -> list[DiagnosticModule]:
        return [self._modules[module_id] for module_id in sorted(self._modules)]


class FrameworkDiagnosticEngine:
    def __init__(self, module: DiagnosticModule) -> None:
        self._module = module

    def solve(self, snapshot: Snapshot, context: dict[str, Any] | None = None) -> DiagnosticSolution:
        evidence = list(self._module.evidence_provider(snapshot, context))
        rule_matches = RuleEngine(self._module.rules).evaluate(evidence)
        candidates = self._module.repair_candidates(evidence, context)
        candidate_order = _candidate_order_from_rules(rule_matches)
        if not candidate_order:
            candidate_order = list(self._module.fallback_repair_order)
        plan = [candidates[candidate_id] for candidate_id in candidate_order]
        diagnosis = self._module.diagnosis_builder(evidence, rule_matches, plan, context)
        return DiagnosticSolution(
            command_name=self._module.command_name,
            diagnosis=diagnosis,
            evidence=evidence,
            repair_plan=plan,
            rule_matches=list(rule_matches),
            supporting_commands=self._module.supporting_commands,
        )

    def plan_repair(
        self,
        snapshot: Snapshot,
        *,
        action_id: str | None = None,
        candidate_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> RepairPlan:
        evidence = list(self._module.evidence_provider(snapshot, context))
        rule_matches = RuleEngine(self._module.rules).evaluate(evidence)
        candidates = self._module.repair_candidates(evidence, context)
        candidate_order = _candidate_order_from_rules(rule_matches) or list(self._module.fallback_repair_order)
        actions = self._module.repair_actions(evidence, candidates, context)
        selected_candidate = _select_repair_candidate(candidates, candidate_order, action_id=action_id, candidate_id=candidate_id)
        if action_id is not None or candidate_id is not None:
            ordered_candidates = [selected_candidate] if selected_candidate else []
        else:
            ordered_candidates = [candidates[candidate_id] for candidate_id in candidate_order if candidate_id in candidates]
        steps: list[RepairStep] = []
        for index, candidate in enumerate(ordered_candidates, start=1):
            candidate_action_id = action_id or candidate.action_id
            action = actions.get(candidate_action_id) if candidate_action_id else None
            skipped_reason = None if action else "No executable repair action is registered for this repair candidate."
            steps.append(RepairStep(index=index, candidate=candidate, action=action, skipped_reason=skipped_reason))
        return RepairPlan(module=self._module.id, command_name=self._module.command_name, steps=tuple(steps))

    def repair_plan(
        self,
        snapshot: Snapshot,
        *,
        action_id: str | None = None,
        candidate_id: str | None = None,
        dry_run: bool = True,
        confirmed: bool = False,
        audit_log: Path | None = None,
        context: dict[str, Any] | None = None,
        snapshot_provider: SnapshotProvider | None = None,
    ) -> RepairPlanResult:
        plan = self.plan_repair(snapshot, action_id=action_id, candidate_id=candidate_id, context=context)
        if not dry_run and not confirmed:
            result = RepairPlanResult(
                module=self._module.id,
                command_name=self._module.command_name,
                status=RepairPlanStatus.BLOCKED,
                dry_run=False,
                confirmed=False,
                plan=plan,
                step_results=tuple(
                    RepairStepResult(
                        index=step.index,
                        candidate_id=step.candidate_id,
                        action_id=step.action_id,
                        status="BLOCKED" if step.action else "SKIPPED",
                        message=(
                            "Execution requires --confirm for non-dry-run repair plan."
                            if step.action
                            else step.skipped_reason or "Skipped."
                        ),
                    )
                    for step in plan.steps
                ),
                message="Execution requires --confirm for non-dry-run repair plan.",
            )
            return _finalize_repair_plan_result(result, audit_log)
        step_results: list[RepairStepResult] = []
        if dry_run:
            for step in plan.steps:
                if step.action is None:
                    step_results.append(
                        RepairStepResult(
                            index=step.index,
                            candidate_id=step.candidate_id,
                            action_id=step.action_id,
                            status="SKIPPED",
                            message=step.skipped_reason or "Skipped.",
                        )
                    )
                    continue
                repair_result = step.action.run(
                    module=self._module.id,
                    command_name=self._module.command_name,
                    candidate_id=step.candidate_id,
                    dry_run=True,
                )
                step_results.append(
                    RepairStepResult(
                        index=step.index,
                        candidate_id=step.candidate_id,
                        action_id=step.action_id,
                        status=repair_result.status.value,
                        repair_result=repair_result,
                        message=repair_result.message,
                    )
                )
            result = RepairPlanResult(
                module=self._module.id,
                command_name=self._module.command_name,
                status=RepairPlanStatus.DRY_RUN,
                dry_run=True,
                confirmed=confirmed,
                plan=plan,
                step_results=tuple(step_results),
                message="Dry run only; no commands were executed and no verification was run.",
            )
            return _finalize_repair_plan_result(result, audit_log)
        verifier = self._module.repair_verifier
        failed_repair_branches = set((context or {}).get("failed_branches", []))
        for step in plan.steps:
            if step.action is None:
                step_results.append(
                    RepairStepResult(
                        index=step.index,
                        candidate_id=step.candidate_id,
                        action_id=step.action_id,
                        status="SKIPPED",
                        message=step.skipped_reason or "Skipped.",
                    )
                )
                continue
            if not _is_safe_for_automatic_continuation(step.action.safety):
                step_results.append(
                    RepairStepResult(
                        index=step.index,
                        candidate_id=step.candidate_id,
                        action_id=step.action_id,
                        status="BLOCKED",
                        message="Step is not safe for automatic continuation; run it manually with an explicit action if needed.",
                    )
                )
                result = RepairPlanResult(
                    module=self._module.id,
                    command_name=self._module.command_name,
                    status=RepairPlanStatus.BLOCKED,
                    dry_run=False,
                    confirmed=True,
                    plan=plan,
                    step_results=tuple(step_results),
                    message="Repair plan stopped before a step that is not safe for automatic continuation.",
                )
                return _finalize_repair_plan_result(result, audit_log)
            repair_result = step.action.run(
                module=self._module.id,
                command_name=self._module.command_name,
                candidate_id=step.candidate_id,
                dry_run=False,
            )
            if repair_result.status is not RepairStatus.SUCCESS:
                step_results.append(
                    RepairStepResult(
                        index=step.index,
                        candidate_id=step.candidate_id,
                        action_id=step.action_id,
                        status=repair_result.status.value,
                        repair_result=repair_result,
                        message=repair_result.message,
                    )
                )
                result = RepairPlanResult(
                    module=self._module.id,
                    command_name=self._module.command_name,
                    status=RepairPlanStatus.BLOCKED
                    if repair_result.status is RepairStatus.BLOCKED
                    else RepairPlanStatus.FAILED,
                    dry_run=False,
                    confirmed=True,
                    plan=plan,
                    step_results=tuple(step_results),
                    message="Repair plan stopped because a repair step did not complete successfully.",
                )
                return _finalize_repair_plan_result(result, audit_log)
            verification = None
            step_status = repair_result.status.value
            if verifier is not None:
                verification_snapshot = snapshot_provider() if snapshot_provider else snapshot
                verifier_context = dict(context or {})
                verifier_context["failed_branches"] = set(failed_repair_branches)
                verification = verifier(verification_snapshot, step.candidate, verifier_context)
                step_status = verification.status
            step_results.append(
                RepairStepResult(
                    index=step.index,
                    candidate_id=step.candidate_id,
                    action_id=step.action_id,
                    status=step_status,
                    repair_result=repair_result,
                    verification=verification,
                    message=repair_result.message,
                )
            )
            if verification and verification.status == "SUCCESS":
                result = RepairPlanResult(
                    module=self._module.id,
                    command_name=self._module.command_name,
                    status=RepairPlanStatus.SUCCESS,
                    dry_run=False,
                    confirmed=True,
                    plan=plan,
                    step_results=tuple(step_results),
                    message="Repair plan stopped after verification succeeded.",
                )
                return _finalize_repair_plan_result(result, audit_log)
            if verification and verification.status == "FAILED":
                failed_repair_branches.add(step.candidate_id)
            if verification and verification.status not in {"FAILED"}:
                result = RepairPlanResult(
                    module=self._module.id,
                    command_name=self._module.command_name,
                    status=RepairPlanStatus.BLOCKED,
                    dry_run=False,
                    confirmed=True,
                    plan=plan,
                    step_results=tuple(step_results),
                    message="Repair plan stopped because verification did not produce a deterministic failure to advance from.",
                )
                return _finalize_repair_plan_result(result, audit_log)
        final_status = RepairPlanStatus.FAILED if step_results else RepairPlanStatus.BLOCKED
        result = RepairPlanResult(
            module=self._module.id,
            command_name=self._module.command_name,
            status=final_status,
            dry_run=False,
            confirmed=True,
            plan=plan,
            step_results=tuple(step_results),
            message="Repair plan exhausted without successful verification.",
        )
        return _finalize_repair_plan_result(result, audit_log)

    def repair(
        self,
        snapshot: Snapshot,
        *,
        action_id: str | None = None,
        candidate_id: str | None = None,
        dry_run: bool = True,
        confirmed: bool = False,
        audit_log: Path | None = None,
        context: dict[str, Any] | None = None,
    ) -> RepairResult:
        evidence = list(self._module.evidence_provider(snapshot, context))
        rule_matches = RuleEngine(self._module.rules).evaluate(evidence)
        candidates = self._module.repair_candidates(evidence, context)
        candidate_order = _candidate_order_from_rules(rule_matches) or list(self._module.fallback_repair_order)
        actions = self._module.repair_actions(evidence, candidates, context)
        selected_candidate = _select_repair_candidate(candidates, candidate_order, action_id=action_id, candidate_id=candidate_id)
        selected_action_id = action_id or (selected_candidate.action_id if selected_candidate else None)
        if selected_action_id is None or selected_action_id not in actions:
            result = RepairResult(
                module=self._module.id,
                command_name=self._module.command_name,
                action_id=selected_action_id or action_id or "",
                candidate_id=selected_candidate.id if selected_candidate else candidate_id,
                status=RepairStatus.NOT_FOUND,
                dry_run=dry_run,
                safety_classification="unknown",
                why_safe="No executable repair action is registered for the selected repair candidate.",
                message="Repair action not found.",
                errors=("Repair action not found.",),
            )
            return _finalize_repair_result(result, audit_log)
        action = actions[selected_action_id]
        if not dry_run and not confirmed:
            result = RepairResult(
                module=self._module.id,
                command_name=self._module.command_name,
                action_id=selected_action_id,
                candidate_id=selected_candidate.id if selected_candidate else candidate_id,
                status=RepairStatus.BLOCKED,
                dry_run=False,
                safety_classification=action.safety,
                why_safe=action.why_safe,
                preconditions=action.preconditions,
                rollback=action.rollback,
                executed_commands=tuple(command.to_json_dict() for command in action.commands),
                message="Execution requires --confirm for non-dry-run repair.",
                files_touched=action.files_touched,
                errors=("Execution requires confirmation via --confirm.",),
            )
            return _finalize_repair_result(result, audit_log)
        result = action.run(
            module=self._module.id,
            command_name=self._module.command_name,
            candidate_id=selected_candidate.id if selected_candidate else candidate_id,
            dry_run=dry_run,
        )
        return _finalize_repair_result(result, audit_log)


def _finalize_repair_result(result: RepairResult, audit_log: Path | None) -> RepairResult:
    if audit_log is None:
        return result
    expanded = audit_log.expanduser()
    audited_result = replace(result, audit_log=str(expanded))
    write_repair_audit_log(expanded, audited_result)
    return audited_result


def _finalize_repair_plan_result(result: RepairPlanResult, audit_log: Path | None) -> RepairPlanResult:
    if audit_log is None:
        return result
    expanded = audit_log.expanduser()
    audited_result = replace(result, audit_log=str(expanded))
    write_repair_plan_audit_log(expanded, audited_result)
    return audited_result


def write_repair_plan_audit_log(path: Path, result: RepairPlanResult) -> None:
    event = repair_plan_audit_event(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=False) + "\n")


def repair_plan_audit_event(result: RepairPlanResult) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "module": result.module,
        "mode": "dry-run-plan" if result.dry_run else "execute-plan",
        "result": result.to_json_dict(),
        "errors": [
            error
            for step_result in result.step_results
            if step_result.repair_result
            for error in step_result.repair_result.errors
        ],
    }


def _repair_safety_value(safety: RepairSafety | str) -> str:
    return safety.value if isinstance(safety, RepairSafety) else safety


def _is_safe_for_automatic_continuation(safety: RepairSafety | str) -> bool:
    return _repair_safety_value(safety) in {RepairSafety.LOW.value, RepairSafety.MODERATE.value, RepairSafety.INTERACTIVE.value}


def write_repair_audit_log(path: Path, result: RepairResult) -> None:
    event = repair_audit_event(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=False) + "\n")


def repair_audit_event(result: RepairResult) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "module": result.module,
        "selected_action": {"id": result.action_id, "candidate_id": result.candidate_id},
        "mode": "dry-run" if result.dry_run else "execute",
        "preconditions": [precondition.to_json_dict() for precondition in result.preconditions],
        "result": result.to_json_dict(),
        "files_touched": list(result.files_touched),
        "rollback": result.rollback.to_json_dict(),
        "errors": list(result.errors),
    }


def evidence_to_json(evidence: DiagnosticEvidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "title": evidence.title,
        "detail": evidence.detail,
        "source": evidence.source,
        "present": evidence.present,
        "confidence": round(evidence.confidence, 4),
        "provenance": list(evidence.provenance),
    }


def rule_match_to_json(match: RuleMatch) -> dict[str, Any]:
    return {
        "id": match.rule_id,
        "diagnosis_id": match.diagnosis_id,
        "matched_required_evidence": list(match.matched_required_evidence),
        "matched_optional_evidence": list(match.matched_optional_evidence),
        "matched_conflicting_evidence": list(match.matched_conflicting_evidence),
        "confidence_contribution": match.confidence_contribution,
        "repair_recommendations": list(match.repair_recommendations),
        "explanation": match.explanation,
    }


def repair_candidate_to_json(candidate: RepairCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "id": candidate.id,
        "title": candidate.title,
        "risk": candidate.risk,
        "manual_action": candidate.manual_action,
        "expected_result": candidate.expected_result,
        "verification_command": candidate.verification_command,
        "fallback_branch": candidate.fallback_branch,
        "evidence_ids": list(candidate.evidence_ids),
    }


def build_support_bundle(
    bundle_path: Path,
    *,
    report_json: dict[str, Any],
    report_text: str,
    command_metadata: dict[str, Any],
    environment: dict[str, Any],
    artifact_sources: dict[str, Path | None] | None = None,
) -> Path:
    bundle_path = bundle_path.expanduser()
    if bundle_path.exists() and not bundle_path.is_dir():
        raise ValueError("Bundle path exists and is not a directory")
    bundle_path.mkdir(parents=True, exist_ok=True)
    write_json_preserving_order(bundle_path / "report.json", report_json)
    (bundle_path / "report.txt").write_text(report_text)
    write_json_preserving_order(bundle_path / "command.json", command_metadata)
    write_json_preserving_order(bundle_path / "environment.json", environment)
    for relative_destination, source in (artifact_sources or {}).items():
        copy_artifacts(source, bundle_path / relative_destination)
    return bundle_path


def write_json_preserving_order(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def copy_artifacts(source: Path | None, destination: Path) -> None:
    if source is None:
        return
    expanded = source.expanduser()
    if not expanded.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    if expanded.is_file():
        shutil.copyfile(expanded, destination / expanded.name)
        return
    for item in sorted(expanded.iterdir(), key=lambda path: path.name):
        if item.is_file():
            shutil.copyfile(item, destination / item.name)


def _select_repair_candidate(
    candidates: dict[str, RepairCandidate],
    candidate_order: Sequence[str],
    *,
    action_id: str | None,
    candidate_id: str | None,
) -> RepairCandidate | None:
    if candidate_id is not None:
        return candidates.get(candidate_id)
    if action_id is not None:
        for candidate in candidates.values():
            if candidate.action_id == action_id:
                return candidate
        return None
    for ranked_candidate_id in candidate_order:
        candidate = candidates.get(ranked_candidate_id)
        if candidate and candidate.action_id:
            return candidate
    return None


def _candidate_order_from_rules(rule_matches: Sequence[RuleMatch]) -> list[str]:
    order: list[str] = []
    for match in rule_matches:
        for recommendation in match.repair_recommendations:
            if recommendation not in order:
                order.append(recommendation)
    return order
