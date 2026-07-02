from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Any

from macos_state_explorer.launchservices.generations import GenerationAnalysis
from macos_state_explorer.launchservices.remediation_plan import RemediationSafety, plan_launchservices_remediation


class GenerationOutcomeState(StrEnum):
    COMPLETED = "COMPLETED"
    REMAINING_PLAN_SAFE = "REMAINING_PLAN_SAFE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    BLOCKED_ACTIVE = "BLOCKED_ACTIVE"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


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
            "next_manual_actions": list(self.next_manual_actions),
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


def build_launchservices_outcome(analysis: GenerationAnalysis, *, completed_generation_ids: list[str] | None = None) -> LaunchServicesOutcome:
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
        item = {
            "product_family": step.product_family,
            "generation_id": step.generation_id,
            "state": state.value,
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
    automatic_complete = not remaining_plan_safe
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
        "reason": "Persistent LaunchServices evidence remains after safe automatic remediation." if automatic_complete and (remaining or blocked) else "No remaining LaunchServices outcome evidence requires automatic execution.",
    }
    next_actions = _next_manual_actions(remaining, skipped, blocked)
    explanation = "Only manual-review generations remain. No additional safe automatic execution exists." if automatic_complete else "Additional PLAN_ONLY_SAFE generations remain eligible for confirmed automatic execution."
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
    lines.append("COMPLETE" if summary.get("automatic_remediation_complete") else "INCOMPLETE")
    lines.append("Further execution requires manual review." if summary.get("automatic_remediation_complete") else "Additional safe automatic execution remains planned.")
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
    lines.extend(["", "Automatic remediation", "STATUS", "COMPLETE" if outcome.automatic_remediation_complete else "INCOMPLETE", "Reason", outcome.explanation, "", "Local Network", "Evidence", outcome.local_network_status["status"], "Reason", outcome.local_network_status["reason"], "", "Next manual actions"])
    for action in outcome.next_manual_actions:
        lines.append(action)
    return "\n".join(lines)


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
