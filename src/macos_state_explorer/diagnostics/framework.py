from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
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
        lines.extend(["", "Rollback", f"- {self.rollback.description}", "", "Commands"])
        if self.executed_commands:
            for command in self.executed_commands:
                rendered = " ".join(command["argv"])
                exit_code = command.get("exit_code")
                suffix = "not run" if exit_code is None else f"exit {exit_code}"
                lines.append(f"- {rendered} ({suffix})")
        else:
            lines.append("- none")
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
    runner: CommandRunner | None = None

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
            )
        runner = self.runner or default_command_runner
        executed: list[dict[str, Any]] = []
        for command in self.commands:
            exit_code, stdout, stderr = runner(list(command.argv))
            record = command.to_json_dict(exit_code=exit_code)
            if stdout:
                record["stdout"] = stdout
            if stderr:
                record["stderr"] = stderr
            executed.append(record)
            if exit_code != 0:
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
                    message=f"Command failed with exit code {exit_code}.",
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
class DiagnosticSolution:
    command_name: str
    diagnosis: str
    evidence: list[DiagnosticEvidence]
    repair_plan: list[RepairCandidate]
    rule_matches: list[RuleMatch] = field(default_factory=list)
    supporting_commands: tuple[str, ...] = ()

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
        return {
            "command": f"solve {self.command_name}",
            "diagnosis": self.diagnosis,
            "evidence": [evidence_to_json(item) for item in sorted(self.evidence, key=lambda item: item.id)],
            "matched_rules": [rule_match_to_json(match) for match in self.rule_matches],
            "repair_candidates": [repair_candidate_to_json(candidate) for candidate in self.repair_plan],
            "next_action": repair_candidate_to_json(self.repair_plan[0]),
        }


EvidenceProvider = Callable[[Snapshot, dict[str, Any] | None], Sequence[DiagnosticEvidence]]
RepairCandidateFactory = Callable[[Sequence[DiagnosticEvidence], dict[str, Any] | None], dict[str, RepairCandidate]]
RepairActionFactory = Callable[
    [Sequence[DiagnosticEvidence], dict[str, RepairCandidate], dict[str, Any] | None],
    dict[str, RepairAction],
]
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

    def repair(
        self,
        snapshot: Snapshot,
        *,
        action_id: str | None = None,
        candidate_id: str | None = None,
        dry_run: bool = True,
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
            return RepairResult(
                module=self._module.id,
                command_name=self._module.command_name,
                action_id=selected_action_id or action_id or "",
                candidate_id=selected_candidate.id if selected_candidate else candidate_id,
                status=RepairStatus.NOT_FOUND,
                dry_run=dry_run,
                safety_classification="unknown",
                why_safe="No executable repair action is registered for the selected repair candidate.",
                message="Repair action not found.",
            )
        return actions[selected_action_id].run(
            module=self._module.id,
            command_name=self._module.command_name,
            candidate_id=selected_candidate.id if selected_candidate else candidate_id,
            dry_run=dry_run,
        )


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
