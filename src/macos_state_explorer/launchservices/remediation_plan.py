from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Any

from macos_state_explorer.launchservices.generations import Generation, GenerationAnalysis, GenerationClassification


class RemediationSafety(StrEnum):
    PLAN_ONLY_SAFE = "PLAN_ONLY_SAFE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"
    BLOCKED_ACTIVE_GENERATION = "BLOCKED_ACTIVE_GENERATION"


@dataclass(frozen=True)
class LaunchServicesRemediationStep:
    step_id: str
    action: str
    product_family: str
    generation_id: str
    target_registrations: list[dict[str, Any]]
    reason: str
    safety: RemediationSafety
    executable: bool
    requires_confirmation: bool
    rollback: str
    expected_effect: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "product_family": self.product_family,
            "generation_id": self.generation_id,
            "target_registrations": list(self.target_registrations),
            "reason": self.reason,
            "safety": self.safety.value,
            "executable": self.executable,
            "requires_confirmation": self.requires_confirmation,
            "rollback": self.rollback,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class LaunchServicesRemediationPlan:
    plan_id: str
    created_at: str
    product_family: str
    active_generation: dict[str, Any] | None
    candidate_generations: list[dict[str, Any]]
    skipped_generations: list[dict[str, Any]]
    safety_summary: dict[str, int]
    steps: list[LaunchServicesRemediationStep]
    verification_commands: list[str]
    warnings: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "launchservices plan",
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "product_family": self.product_family,
            "active_generation": self.active_generation,
            "candidate_generations": list(self.candidate_generations),
            "skipped_generations": list(self.skipped_generations),
            "safety_summary": dict(self.safety_summary),
            "steps": [step.to_json_dict() for step in self.steps],
            "verification_commands": list(self.verification_commands),
            "warnings": list(self.warnings),
        }


def plan_launchservices_remediation(analysis: GenerationAnalysis) -> LaunchServicesRemediationPlan:
    active_by_product = _active_generations_by_product(analysis.generations)
    candidate_generations: list[dict[str, Any]] = []
    skipped_generations: list[dict[str, Any]] = []
    steps: list[LaunchServicesRemediationStep] = []

    for generation in _ordered_generations(analysis.generations):
        skip_safety = _skip_safety(generation)
        if skip_safety is not None:
            skipped_generations.append(_generation_plan_dict(generation, skip_safety, _skip_reason(generation, skip_safety)))
            continue
        step = _step_for_generation(generation, len(steps) + 1)
        if step is None:
            skipped_generations.append(_generation_plan_dict(generation, RemediationSafety.BLOCKED_UNKNOWN, "Generation is not classified as safe planning material."))
            continue
        candidate_generations.append(_generation_plan_dict(generation, step.safety, step.reason))
        steps.append(step)

    active_generation = _active_generation_json(active_by_product)
    warnings = ["No active generation is selected for cleanup"]
    if any(item["safety"] == RemediationSafety.BLOCKED_UNKNOWN.value for item in skipped_generations):
        warnings.append("Unknown generations are skipped until reviewed manually.")
    if not steps:
        warnings.append("No selective remediation steps were planned.")
    safety_counts = Counter(step.safety.value for step in steps)
    safety_counts.update(item["safety"] for item in skipped_generations)
    return LaunchServicesRemediationPlan(
        plan_id=_plan_id(analysis),
        created_at="1970-01-01T00:00:00Z",
        product_family="Chromium-family",
        active_generation=active_generation,
        candidate_generations=candidate_generations,
        skipped_generations=skipped_generations,
        safety_summary={key: safety_counts.get(key, 0) for key in [safety.value for safety in RemediationSafety]},
        steps=steps,
        verification_commands=[
            "mse launchservices analyze --json",
            "mse launchservices generations --json",
            "mse launchservices plan --json",
            "mse solve local-network --json",
        ],
        warnings=warnings,
    )


def render_remediation_plan(plan: LaunchServicesRemediationPlan) -> str:
    lines = ["LaunchServices remediation plan", "", f"Plan ID: {plan.plan_id}", f"Product family: {plan.product_family}"]
    active = plan.active_generation or {}
    if active.get("by_product"):
        for product in sorted(active["by_product"]):
            info = active["by_product"][product]
            lines.append(f"Product family: {product}")
            lines.append(f"Active generation: {info.get('version') or '<unknown>'}")
    else:
        lines.append("Active generation: none detected")
    lines.extend(["", "planned candidate generations"])
    if plan.steps:
        for step in plan.steps:
            safety = "manual review" if step.safety == RemediationSafety.MANUAL_REVIEW_REQUIRED else step.safety.value
            noun = "registration" if len(step.target_registrations) == 1 else "registrations"
            lines.append(f"- {step.product_family} {step.generation_id}")
            lines.append(f"  Reason: {step.reason}")
            lines.append(f"  Registration count: {len(step.target_registrations)} {noun}")
            lines.append(f"  Safety: {safety}")
            lines.append(f"  Executable in future: {'yes' if step.executable else 'no'}")
    else:
        lines.append("- none")
    lines.extend(["", "Skipped generations"])
    if plan.skipped_generations:
        for generation in plan.skipped_generations:
            lines.append(f"- {generation['product_family']} {generation['generation_id']} — {generation['reason']} ({generation['safety']})")
    else:
        lines.append("- none")
    lines.extend(["", "Verification commands"])
    for command in plan.verification_commands:
        lines.append(f"- {command}")
    if plan.warnings:
        lines.extend(["", "Warnings"])
        for warning in plan.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def remediation_plan_summary(plan: LaunchServicesRemediationPlan) -> dict[str, Any]:
    product_summary: dict[str, Counter[str]] = {}
    for step in plan.steps:
        counter = product_summary.setdefault(step.product_family, Counter())
        if step.action == "plan_unregister_obsolete_generation":
            counter["obsolete"] += 1
        elif step.action == "plan_review_mounted_installer_generation":
            counter["mounted_installer"] += 1
        elif step.action == "plan_review_trash_generation":
            counter["trash"] += 1
        elif step.action == "plan_review_stale_updater_generation":
            counter["stale_updater"] += 1
    product_summaries = [
        {
            "product_family": product,
            "obsolete_generation_count": counts.get("obsolete", 0),
            "mounted_installer_generation_count": counts.get("mounted_installer", 0),
            "trash_generation_count": counts.get("trash", 0),
            "stale_updater_generation_count": counts.get("stale_updater", 0),
        }
        for product, counts in sorted(product_summary.items())
    ]
    return {
        "plan_id": plan.plan_id,
        "step_count": len(plan.steps),
        "product_summaries": product_summaries,
        "safety_summary": dict(plan.safety_summary),
        "warnings": list(plan.warnings),
    }


def render_remediation_plan_summary(summary: dict[str, Any]) -> str:
    lines = ["Selective LaunchServices remediation plan"]
    products = summary.get("product_summaries") or []
    if not products:
        lines.append("- No LaunchServices remediation candidates are planned.")
    for product in products:
        family = product["product_family"]
        obsolete = int(product.get("obsolete_generation_count", 0))
        mounted = int(product.get("mounted_installer_generation_count", 0))
        trash = int(product.get("trash_generation_count", 0))
        updater = int(product.get("stale_updater_generation_count", 0))
        if obsolete:
            lines.append(f"- {family}: {_count_phrase(obsolete, 'obsolete generation')} can be planned for manual-review cleanup")
        if mounted:
            lines.append(f"- {family}: {_count_phrase(mounted, 'mounted installer generation')} requires manual review")
        if trash:
            lines.append(f"- {family}: {_count_phrase(trash, 'Trash generation')} requires manual review")
        if updater:
            lines.append(f"- {family}: {_count_phrase(updater, 'stale updater generation')} requires manual review")
    for warning in summary.get("warnings") or []:
        lines.append(f"- {warning}")
    return "\n".join(lines)


def _active_generations_by_product(generations: list[Generation]) -> dict[str, Generation]:
    active: dict[str, Generation] = {}
    for generation in generations:
        if generation.classification != GenerationClassification.ACTIVE:
            continue
        current = active.get(generation.product_family)
        if current is None or _version_key(generation.version) > _version_key(current.version):
            active[generation.product_family] = generation
    return active


def _ordered_generations(generations: list[Generation]) -> list[Generation]:
    return sorted(generations, key=lambda item: (item.product_family, _classification_rank(item.classification), _version_key(item.version), item.generation_id))


def _skip_safety(generation: Generation) -> RemediationSafety | None:
    if generation.classification == GenerationClassification.ACTIVE:
        return RemediationSafety.BLOCKED_ACTIVE_GENERATION
    if generation.classification == GenerationClassification.UNKNOWN:
        return RemediationSafety.BLOCKED_UNKNOWN
    return None


def _skip_reason(generation: Generation, safety: RemediationSafety) -> str:
    if safety == RemediationSafety.BLOCKED_ACTIVE_GENERATION:
        return "Active/current generation is never selected for cleanup."
    if generation.classification == GenerationClassification.UNKNOWN:
        return "Unknown generation requires manual classification before cleanup planning."
    return "Generation skipped by safety policy."


def _step_for_generation(generation: Generation, index: int) -> LaunchServicesRemediationStep | None:
    if _is_volume_generation(generation):
        action = "plan_review_mounted_installer_generation"
        safety = RemediationSafety.MANUAL_REVIEW_REQUIRED
        reason = "Mounted or nonexistent installer volume registrations require manual review before cleanup."
    elif generation.classification == GenerationClassification.STALE and generation.product_family in {"Google Chrome", "Microsoft Edge", "Chromium", "Brave", "Arc"}:
        action = "plan_unregister_obsolete_generation"
        safety = RemediationSafety.PLAN_ONLY_SAFE
        reason = "Obsolete helper/framework/app generation is superseded by an active generation."
    elif generation.classification == GenerationClassification.MISSING and generation.product_family in {"Google Chrome", "Microsoft Edge", "Chromium", "Brave", "Arc"}:
        action = "plan_unregister_missing_generation"
        safety = RemediationSafety.MANUAL_REVIEW_REQUIRED
        reason = "Missing old app/helper registration can be reviewed for selective unregister planning."
    elif generation.classification == GenerationClassification.MOUNTED_INSTALLER:
        action = "plan_review_mounted_installer_generation"
        safety = RemediationSafety.MANUAL_REVIEW_REQUIRED
        reason = "Mounted installer registrations may be transient and require manual review before cleanup."
    elif generation.classification == GenerationClassification.TRASH:
        action = "plan_review_trash_generation"
        safety = RemediationSafety.MANUAL_REVIEW_REQUIRED
        reason = "Trash registrations require manual review before cleanup planning."
    elif generation.classification == GenerationClassification.STALE and generation.product_family in {"GoogleUpdater", "EdgeUpdater"}:
        action = "plan_review_stale_updater_generation"
        safety = RemediationSafety.MANUAL_REVIEW_REQUIRED
        reason = "Stale updater generation is related but not part of the browser active generation."
    else:
        return None
    return LaunchServicesRemediationStep(
        step_id=f"ls-plan-step-{index:03d}",
        action=action,
        product_family=generation.product_family,
        generation_id=generation.generation_id,
        target_registrations=[registration.to_json_dict() for registration in generation.registrations],
        reason=reason,
        safety=safety,
        executable=False,
        requires_confirmation=True,
        rollback="No automated mutation is performed in this plan-only PR; rollback is not needed for planning output.",
        expected_effect="Future execution would selectively unregister only this generation's target registrations after validation.",
    )


def _generation_plan_dict(generation: Generation, safety: RemediationSafety, reason: str) -> dict[str, Any]:
    return {
        "product_family": generation.product_family,
        "generation_id": generation.generation_id,
        "version": generation.version,
        "classification": generation.classification.value,
        "registration_count": len(generation.registrations),
        "safety": safety.value,
        "reason": reason,
    }


def _is_volume_generation(generation: Generation) -> bool:
    if (generation.installation_root or "").startswith("/Volumes/"):
        return True
    return any((registration.path or "").startswith("/Volumes/") for registration in generation.registrations)


def _active_generation_json(active_by_product: dict[str, Generation]) -> dict[str, Any] | None:
    if not active_by_product:
        return None
    by_product = {
        product: {
            "generation_id": generation.generation_id,
            "version": generation.version,
            "registration_count": len(generation.registrations),
        }
        for product, generation in sorted(active_by_product.items())
    }
    primary = by_product.get("Google Chrome") or next(iter(by_product.values()))
    return {"generation_id": primary["generation_id"], "version": primary["version"], "by_product": by_product}


def _plan_id(analysis: GenerationAnalysis) -> str:
    basis = "|".join(generation.generation_id for generation in _ordered_generations(analysis.generations))
    digest = hashlib.sha256(basis.encode()).hexdigest()[:12]
    return f"ls-plan-{digest}"


def _classification_rank(classification: GenerationClassification) -> int:
    return {
        GenerationClassification.STALE: 0,
        GenerationClassification.MISSING: 1,
        GenerationClassification.MOUNTED_INSTALLER: 2,
        GenerationClassification.TRASH: 3,
        GenerationClassification.ACTIVE: 4,
        GenerationClassification.PARTIAL: 5,
        GenerationClassification.UNKNOWN: 6,
    }[classification]


def _version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    parts: list[int] = []
    for part in value.replace("-", ".").split("."):
        if part.isdecimal():
            parts.append(int(part))
        else:
            break
    return tuple(parts)


def _count_phrase(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"
