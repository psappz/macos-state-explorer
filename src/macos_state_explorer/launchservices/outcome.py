from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from macos_state_explorer.launchservices.generations import GenerationAnalysis
from macos_state_explorer.launchservices.remediation_plan import RemediationSafety, plan_launchservices_remediation


class GenerationOutcomeState(StrEnum):
    COMPLETED = "COMPLETED"
    REMAINING_PLAN_SAFE = "REMAINING_PLAN_SAFE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    BLOCKED_ACTIVE = "BLOCKED_ACTIVE"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AutomaticRemediationStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    EXHAUSTED = "EXHAUSTED"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExecutePlanAuditHistory:
    by_generation: dict[str, str]
    source: str | None = None
    sources: list[str] | None = None


@dataclass(frozen=True)
class LaunchServicesOutcome:
    outcome_id: str
    timestamp: str
    product_families: list[str]
    completed_generations: list[dict[str, Any]]
    remaining_generations: list[dict[str, Any]]
    skipped_generations: list[dict[str, Any]]
    blocked_generations: list[dict[str, Any]]
    active_generations: list[dict[str, Any]]
    evidence_status: dict[str, Any]
    local_network_status: dict[str, Any]
    automatic_remediation_complete: bool
    automatic_remediation_status: str
    audit_history: dict[str, Any]
    next_manual_actions: list[str]
    confidence: float
    explanation: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "launchservices outcome",
            "outcome_id": self.outcome_id,
            "timestamp": self.timestamp,
            "product_families": list(self.product_families),
            "completed_generations": list(self.completed_generations),
            "remaining_generations": list(self.remaining_generations),
            "skipped_generations": list(self.skipped_generations),
            "blocked_generations": list(self.blocked_generations),
            "active_generations": list(self.active_generations),
            "evidence_status": dict(self.evidence_status),
            "local_network_status": dict(self.local_network_status),
            "automatic_remediation_complete": self.automatic_remediation_complete,
            "automatic_remediation_status": self.automatic_remediation_status,
            "audit_history": dict(self.audit_history),
            "next_manual_actions": list(self.next_manual_actions),
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


def build_launchservices_outcome(
    analysis: GenerationAnalysis,
    *,
    completed_generation_ids: list[str] | None = None,
    audit_history: ExecutePlanAuditHistory | None = None,
) -> LaunchServicesOutcome:
    completed_ids = sorted(set(completed_generation_ids or []))
    plan = plan_launchservices_remediation(analysis)
    product_families = sorted({generation.product_family for generation in analysis.generations} | {step.product_family for step in plan.steps})
    completed = [_generation_stub(generation_id, GenerationOutcomeState.COMPLETED) for generation_id in completed_ids]
    remaining: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []

    for step in plan.steps:
        state = GenerationOutcomeState.REMAINING_PLAN_SAFE if step.safety == RemediationSafety.PLAN_ONLY_SAFE else GenerationOutcomeState.MANUAL_REVIEW_REQUIRED
        history_state = _history_state_for_step(step.generation_id, step.safety, audit_history)
        if state == GenerationOutcomeState.REMAINING_PLAN_SAFE and history_state == "attempted_removed":
            history_state = "attempted_but_present_again"
        item = {
            "product_family": step.product_family,
            "generation_id": step.generation_id,
            "state": state.value,
            "history_state": history_state,
            "registration_count": len(step.target_registrations),
            "safety": step.safety.value,
            "reason": step.reason,
            "action": step.action,
        }
        if state == GenerationOutcomeState.REMAINING_PLAN_SAFE:
            remaining.append(item)
        else:
            remaining.append(item)
            skipped.append(item)

    for generation in plan.skipped_generations:
        safety = generation.get("safety")
        if safety == RemediationSafety.BLOCKED_ACTIVE_GENERATION.value:
            state = GenerationOutcomeState.BLOCKED_ACTIVE
        elif safety == RemediationSafety.BLOCKED_UNKNOWN.value:
            state = GenerationOutcomeState.BLOCKED_UNKNOWN
        else:
            state = GenerationOutcomeState.NOT_APPLICABLE
        item = {
            "product_family": generation.get("product_family"),
            "generation_id": generation.get("generation_id"),
            "version": generation.get("version"),
            "classification": generation.get("classification"),
            "registration_count": generation.get("registration_count", 0),
            "state": state.value,
            "history_state": _history_state_for_blocked(state),
            "safety": safety,
            "reason": generation.get("reason"),
        }
        if state == GenerationOutcomeState.BLOCKED_ACTIVE:
            active.append(item)
        elif state == GenerationOutcomeState.BLOCKED_UNKNOWN:
            blocked.append(item)
        else:
            skipped.append(item)

    remaining_plan_safe = [item for item in remaining if item["state"] == GenerationOutcomeState.REMAINING_PLAN_SAFE.value]
    automatic_status = _automatic_status(remaining_plan_safe)
    automatic_complete = automatic_status == AutomaticRemediationStatus.EXHAUSTED.value and not any(item.get("history_state") == "attempted_unknown" for item in remaining_plan_safe)
    manual_count = len([item for item in remaining if item["state"] == GenerationOutcomeState.MANUAL_REVIEW_REQUIRED.value])
    blocked_count = len(blocked) + len(active)
    evidence_status = {
        "status": "REMAINING" if remaining else "CLEAR",
        "remaining_generation_count": len(remaining),
        "manual_review_generation_count": manual_count,
        "blocked_generation_count": blocked_count,
    }
    local_network_status = {
        "status": "UNCHANGED" if remaining or blocked else "CONSISTENT",
        "automatic_remediation_status": automatic_status,
        "reason": _local_network_reason(automatic_status, bool(remaining or blocked)),
    }
    next_actions = _next_manual_actions(remaining, skipped, blocked)
    explanation = _automatic_explanation(automatic_status)
    digest_basis = "|".join([*completed_ids, *(str(item.get("generation_id")) for item in remaining), *(str(item.get("generation_id")) for item in blocked), *(str(item.get("generation_id")) for item in active)])
    outcome_id = f"ls-outcome-{hashlib.sha256(digest_basis.encode()).hexdigest()[:12]}"
    return LaunchServicesOutcome(
        outcome_id=outcome_id,
        timestamp="1970-01-01T00:00:00Z",
        product_families=product_families,
        completed_generations=completed,
        remaining_generations=remaining,
        skipped_generations=skipped,
        blocked_generations=blocked,
        active_generations=active,
        evidence_status=evidence_status,
        local_network_status=local_network_status,
        automatic_remediation_complete=automatic_complete,
        automatic_remediation_status=automatic_status,
        audit_history=_audit_history_summary(audit_history),
        next_manual_actions=next_actions,
        confidence=0.9 if automatic_complete else 0.85,
        explanation=explanation,
    )


def outcome_summary(outcome: LaunchServicesOutcome) -> dict[str, Any]:
    remaining_counts = Counter(item.get("action") for item in outcome.remaining_generations)
    return {
        "outcome_id": outcome.outcome_id,
        "completed": len(outcome.completed_generations),
        "remaining": len(outcome.remaining_generations),
        "blocked": len(outcome.blocked_generations) + len(outcome.active_generations),
        "automatic_remediation_complete": outcome.automatic_remediation_complete,
        "automatic_remediation_status": outcome.automatic_remediation_status,
        "audit_informed": bool(outcome.audit_history.get("source_count")),
        "remaining_trash_generations": remaining_counts.get("plan_review_trash_generation", 0),
        "remaining_mounted_installer_generations": remaining_counts.get("plan_review_mounted_installer_generation", 0),
        "remaining_updater_generations": remaining_counts.get("plan_review_stale_updater_generation", 0),
        "next_manual_actions": list(outcome.next_manual_actions),
        "explanation": outcome.explanation,
    }


def render_outcome_summary(summary: dict[str, Any]) -> str:
    lines = ["Automatic LaunchServices remediation"]
    lines.append(f"Completed: {summary.get('completed', 0)} obsolete Chrome generations")
    lines.append("Remaining:")
    lines.append(f"- {summary.get('remaining_trash_generations', 0)} Trash generation")
    lines.append(f"- {summary.get('remaining_mounted_installer_generations', 0)} mounted installer generation")
    lines.append(f"- {summary.get('remaining_updater_generations', 0)} updater generations")
    lines.append("Automatic remediation:")
    status = str(summary.get("automatic_remediation_status") or ("EXHAUSTED" if summary.get("automatic_remediation_complete") else "INCOMPLETE"))
    lines.append(status)
    lines.append("Further execution requires manual review or prior safe attempts did not persist." if status in {"EXHAUSTED", "UNKNOWN"} else "Additional safe automatic execution remains planned.")
    return "\n".join(lines)


def render_launchservices_outcome(outcome: LaunchServicesOutcome) -> str:
    lines = ["LaunchServices remediation outcome", ""]
    for product in outcome.product_families:
        lines.append(product)
        lines.append("")
    lines.append("Completed")
    if outcome.completed_generations:
        for item in outcome.completed_generations:
            lines.append(f"✓ Generation {_display_generation(item)}")
    else:
        lines.append("- none recorded in current snapshot")
    lines.append("")
    lines.append("Remaining")
    remaining = [item for item in outcome.remaining_generations if item.get("state") == GenerationOutcomeState.MANUAL_REVIEW_REQUIRED.value]
    if remaining:
        for item in remaining:
            lines.append(f"• {_manual_label(item)}")
    else:
        lines.append("- none")
    plan_safe = [item for item in outcome.remaining_generations if item.get("state") == GenerationOutcomeState.REMAINING_PLAN_SAFE.value]
    if plan_safe:
        lines.append("Plan-safe remaining")
        for item in plan_safe:
            lines.append(f"• Generation {_display_generation(item)}")
    lines.append("")
    lines.append("Manual review")
    if outcome.skipped_generations:
        for item in outcome.skipped_generations:
            lines.append(f"• {item.get('product_family')} generations")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Protected")
    for item in outcome.active_generations:
        lines.append(f"• Active {item.get('product_family')} generation")
    if not outcome.active_generations:
        lines.append("- none")
    lines.extend(["", "Automatic remediation", "STATUS", outcome.automatic_remediation_status, "Reason", outcome.explanation, "", "Local Network", "Evidence", outcome.local_network_status["status"], "Reason", outcome.local_network_status["reason"], "", "Next manual actions"])
    for action in outcome.next_manual_actions:
        lines.append(action)
    return "\n".join(lines)


def read_execute_plan_audit_history(path: Path | Sequence[Path] | None) -> ExecutePlanAuditHistory | None:
    if path is None:
        return None
    paths = list(path) if isinstance(path, Sequence) and not isinstance(path, (str, bytes, Path)) else [path]
    by_generation: dict[str, str] = {}
    sources: list[str] = []
    for raw_path in paths:
        expanded = Path(raw_path).expanduser()
        sources.append(str(expanded))
        if not expanded.exists():
            continue
        for line in expanded.read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event") == "launchservices_execute_plan_generation":
                _apply_generation_audit_event(by_generation, event)
            elif event.get("event") == "launchservices_execute_plan_run" and event.get("confirmed") is True:
                _apply_run_audit_event(by_generation, event)
    return ExecutePlanAuditHistory(by_generation=by_generation, source=sources[0] if sources else None, sources=sources)


def _apply_generation_audit_event(by_generation: dict[str, str], event: dict[str, Any]) -> None:
    generation_id = event.get("generation_id")
    if not isinstance(generation_id, str) or not generation_id:
        return
    errors = event.get("errors")
    if isinstance(errors, list) and errors:
        by_generation[generation_id] = "attempted_unknown"
        return
    verification_value = event.get("verification")
    verification = verification_value if isinstance(verification_value, dict) else {}
    if verification.get("generation_removed") is True:
        by_generation[generation_id] = "attempted_removed"
    elif verification.get("generation_removed") is False:
        by_generation[generation_id] = "attempted_no_persistent_change"
    else:
        by_generation[generation_id] = _state_for_result(str(verification.get("result") or "UNKNOWN"))


def _apply_run_audit_event(by_generation: dict[str, str], event: dict[str, Any]) -> None:
    status = str(event.get("final_verdict") or event.get("status") or "UNKNOWN")
    generation_diff_value = event.get("generation_diff")
    generation_diff = generation_diff_value if isinstance(generation_diff_value, dict) else {}
    for generation_id in _audit_generation_ids(generation_diff.get("removed")):
        by_generation[generation_id] = "attempted_removed"
    no_change_state = _state_for_result(status)
    for key in ("regenerated", "still_present", "persisted"):
        for generation_id in _audit_generation_ids(generation_diff.get(key)):
            by_generation[generation_id] = no_change_state
    if status in {"NO_MUTATION", "MUTATED_BUT_REGENERATED", "MUTATION_FAILED", "UNKNOWN"}:
        for step in event.get("executed_steps", []):
            if isinstance(step, dict) and isinstance(step.get("generation_id"), str):
                by_generation[step["generation_id"]] = no_change_state


def _state_for_result(result: str) -> str:
    if result == "MUTATED_AND_REMOVED":
        return "attempted_removed"
    if result == "UNKNOWN":
        return "attempted_unknown"
    if result == "MUTATION_FAILED":
        return "attempted_failed"
    return "attempted_no_persistent_change"


def _audit_history_summary(audit_history: ExecutePlanAuditHistory | None) -> dict[str, Any]:
    if audit_history is None:
        return {"source_count": 0, "sources": [], "generation_count": 0}
    sources = list(audit_history.sources or ([audit_history.source] if audit_history.source else []))
    return {"source_count": len(sources), "sources": sources, "generation_count": len(audit_history.by_generation)}

def _history_state_for_step(generation_id: str, safety: RemediationSafety, audit_history: ExecutePlanAuditHistory | None) -> str:
    if safety == RemediationSafety.MANUAL_REVIEW_REQUIRED:
        return "manual_review_required"
    if audit_history is None:
        return "eligible_not_attempted"
    return audit_history.by_generation.get(generation_id, "eligible_not_attempted")


def _history_state_for_blocked(state: GenerationOutcomeState) -> str:
    if state == GenerationOutcomeState.BLOCKED_ACTIVE:
        return "blocked_active"
    if state == GenerationOutcomeState.BLOCKED_UNKNOWN:
        return "blocked_unknown"
    return "manual_review_required"


def _automatic_status(plan_safe: list[dict[str, Any]]) -> str:
    if not plan_safe:
        return AutomaticRemediationStatus.EXHAUSTED.value
    states = {str(item.get("history_state")) for item in plan_safe}
    if "eligible_not_attempted" in states:
        return AutomaticRemediationStatus.AVAILABLE.value
    if states & {"attempted_unknown", "attempted_but_present_again", "attempted_failed"}:
        return AutomaticRemediationStatus.UNKNOWN.value
    if states <= {"attempted_removed"}:
        return AutomaticRemediationStatus.EXHAUSTED.value
    if states & {"attempted_no_persistent_change", "attempted_removed"}:
        return AutomaticRemediationStatus.EXHAUSTED.value
    return AutomaticRemediationStatus.INCOMPLETE.value


def _automatic_explanation(status: str) -> str:
    if status == AutomaticRemediationStatus.AVAILABLE.value:
        return "Additional PLAN_ONLY_SAFE generations remain eligible_not_attempted; safe automatic execution remains available."
    if status == AutomaticRemediationStatus.UNKNOWN.value:
        return "PLAN_ONLY_SAFE generations were attempted but persistent removal is unknown or the generation is present again. Do not report them as simply eligible."
    if status == AutomaticRemediationStatus.EXHAUSTED.value:
        return "Only manual-review generations remain or prior PLAN_ONLY_SAFE attempts produced no persistent change. No additional safe automatic execution exists."
    return "Automatic remediation is incomplete because outcome history is insufficient."


def _local_network_reason(status: str, has_remaining_evidence: bool) -> str:
    if status == AutomaticRemediationStatus.AVAILABLE.value:
        return "Persistent LaunchServices evidence remains and safe automatic remediation is still available."
    if status == AutomaticRemediationStatus.UNKNOWN.value:
        return "Persistent LaunchServices evidence remains after an audit history with unknown persistent mutation outcome."
    if status == AutomaticRemediationStatus.EXHAUSTED.value and has_remaining_evidence:
        return "Persistent LaunchServices evidence remains after safe automatic remediation reached its limit."
    return "No remaining LaunchServices outcome evidence requires automatic execution."


def _audit_generation_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value if isinstance(item, str) and item)


def _generation_stub(generation_id: str, state: GenerationOutcomeState) -> dict[str, Any]:
    product_family, version, *_ = generation_id.split("|") + [None, None]
    return {"product_family": product_family, "generation_id": generation_id, "version": version, "state": state.value, "registration_count": 0, "reason": "Recorded as completed by prior remediation context."}


def _next_manual_actions(remaining: list[dict[str, Any]], skipped: list[dict[str, Any]], blocked: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if any(item.get("action") == "plan_review_trash_generation" for item in remaining):
        actions.append("Review Trash generation")
    if any(item.get("action") == "plan_review_mounted_installer_generation" for item in remaining):
        actions.append("Review mounted installer generation")
    if any(item.get("action") == "plan_review_stale_updater_generation" for item in remaining + skipped):
        actions.append("Review updater generations")
    if any(item.get("product_family") == "Google Chrome" for item in remaining):
        actions.append("Optional Chrome reinstall")
    if blocked:
        actions.append("Review unknown LaunchServices registrations")
    actions.append("No automatic execution recommended.")
    return actions


def _display_generation(item: dict[str, Any]) -> str:
    return str(item.get("version") or item.get("generation_id"))


def _manual_label(item: dict[str, Any]) -> str:
    action = item.get("action")
    if action == "plan_review_trash_generation":
        return "Trash generation"
    if action == "plan_review_mounted_installer_generation":
        return "Mounted installer generation"
    if action == "plan_review_stale_updater_generation":
        return f"{item.get('product_family')} generations"
    return f"{item.get('product_family')} generation"
