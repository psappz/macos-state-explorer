from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
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
DiagnosisBuilder = Callable[
    [Sequence[DiagnosticEvidence], Sequence[RuleMatch], Sequence[RepairCandidate], dict[str, Any] | None],
    str,
]


@dataclass(frozen=True)
class DiagnosticModule:
    id: str
    command_name: str
    evidence_provider: EvidenceProvider
    rules: Sequence[DiagnosticRule]
    repair_candidates: RepairCandidateFactory
    diagnosis_builder: DiagnosisBuilder
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


def _candidate_order_from_rules(rule_matches: Sequence[RuleMatch]) -> list[str]:
    order: list[str] = []
    for match in rule_matches:
        for recommendation in match.repair_recommendations:
            if recommendation not in order:
                order.append(recommendation)
    return order
