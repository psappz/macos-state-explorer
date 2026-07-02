from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from typing import Any

from macos_state_explorer.launchservices.generations import Generation, GenerationAnalysis, GenerationClassification
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance
from macos_state_explorer.launchservices.regeneration import LaunchServicesRegeneration, build_launchservices_regeneration

CATEGORY_ORDER = ["trash", "mounted_installer", "updater", "unknown_chrome_application"]
CATEGORY_TITLES = {
    "trash": "Trash registrations",
    "mounted_installer": "Mounted installer registrations",
    "updater": "Updater registrations",
    "unknown_chrome_application": "Unknown regenerator Chrome application generations",
}


@dataclass(frozen=True)
class CleanupChecklistItem:
    item_id: str
    category: str
    generation_id: str
    producer: str
    regenerator: str
    confidence: float
    classification: str
    paths: list[str]
    registration_ids: list[str]
    why_automatic_cleanup_not_recommended: str
    exact_manual_action: str
    verification_command: str
    expected_post_condition: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "category": self.category,
            "generation_id": self.generation_id,
            "producer": self.producer,
            "regenerator": self.regenerator,
            "confidence": round(self.confidence, 4),
            "classification": self.classification,
            "paths": list(self.paths),
            "registration_ids": list(self.registration_ids),
            "why_automatic_cleanup_not_recommended": self.why_automatic_cleanup_not_recommended,
            "exact_manual_action": self.exact_manual_action,
            "verification_command": self.verification_command,
            "expected_post_condition": self.expected_post_condition,
        }


@dataclass(frozen=True)
class LaunchServicesCleanupChecklist:
    checklist_id: str
    timestamp: str
    items: list[CleanupChecklistItem]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "launchservices cleanup-checklist",
            "checklist_id": self.checklist_id,
            "timestamp": self.timestamp,
            "item_count": len(self.items),
            "summary": cleanup_checklist_summary(self),
            "items": [item.to_json_dict() for item in self.items],
            "read_only": True,
            "mutation_performed": False,
        }


def build_launchservices_cleanup_checklist(
    analysis: GenerationAnalysis,
    *,
    trace_analysis: dict[str, Any] | None = None,
    regeneration: LaunchServicesRegeneration | None = None,
) -> LaunchServicesCleanupChecklist:
    effective_regeneration = regeneration or build_launchservices_regeneration(analysis, trace_analysis=trace_analysis)
    regeneration_by_id = {item.generation_id: item for item in effective_regeneration.generations}
    producer_by_id = _producer_by_generation(analysis)
    items: list[CleanupChecklistItem] = []
    for generation in analysis.generations:
        category = _category_for_generation(generation, regeneration_by_id.get(generation.generation_id))
        if category is None:
            continue
        regen = regeneration_by_id.get(generation.generation_id)
        item = _item_for_generation(generation, category, producer_by_id.get(generation.generation_id, "Unknown"), regen)
        items.append(item)
    items.sort(key=lambda item: (CATEGORY_ORDER.index(item.category), item.generation_id))
    digest_basis = "|".join(f"{item.item_id}:{item.exact_manual_action}" for item in items)
    checklist_id = f"ls-cleanup-checklist-{hashlib.sha256(digest_basis.encode()).hexdigest()[:12]}"
    return LaunchServicesCleanupChecklist(checklist_id=checklist_id, timestamp="1970-01-01T00:00:00Z", items=items)


def cleanup_checklist_summary(checklist: LaunchServicesCleanupChecklist) -> dict[str, Any]:
    counts = Counter(item.category for item in checklist.items)
    counts_by_category = {category: counts.get(category, 0) for category in CATEGORY_ORDER if counts.get(category, 0)}
    first = checklist.items[0].exact_manual_action if checklist.items else "No manual cleanup checklist items remain."
    return {
        "checklist_id": checklist.checklist_id,
        "item_count": len(checklist.items),
        "counts_by_category": counts_by_category,
        "item_ids": [item.item_id for item in checklist.items],
        "first_recommended_manual_action": first,
        "read_only": True,
        "mutation_performed": False,
    }


def local_network_cleanup_checklist_summary(checklist: LaunchServicesCleanupChecklist) -> dict[str, Any]:
    summary = cleanup_checklist_summary(checklist)
    return {
        "item_count": summary["item_count"],
        "counts_by_category": summary["counts_by_category"],
        "item_ids": summary["item_ids"],
        "first_recommended_manual_action": summary["first_recommended_manual_action"],
        "read_only": True,
        "mutation_performed": False,
    }


def render_cleanup_checklist_summary(summary: dict[str, Any]) -> str:
    counts_value = summary.get("counts_by_category")
    counts = counts_value if isinstance(counts_value, dict) else {}
    count_parts = ", ".join(f"{category}: {count}" for category, count in sorted(counts.items())) or "none"
    return "\n".join(
        [
            "LaunchServices cleanup checklist",
            f"- Counts by category: {count_parts}",
            f"- First recommended manual action: {summary.get('first_recommended_manual_action', 'none')}",
            "- No automatic cleanup is performed by this checklist.",
        ]
    )


def render_launchservices_cleanup_checklist(checklist: LaunchServicesCleanupChecklist) -> str:
    lines = ["LaunchServices cleanup checklist", "No automatic cleanup is performed. This is a manual safety bridge."]
    for category in CATEGORY_ORDER:
        lines.extend(["", CATEGORY_TITLES[category]])
        category_items = [item for item in checklist.items if item.category == category]
        if not category_items:
            lines.append("- none")
            continue
        for item in category_items:
            lines.append(f"- {item.generation_id}")
            lines.append(f"  Producer: {item.producer}")
            lines.append(f"  Regenerator: {item.regenerator}")
            lines.append(f"  Confidence: {item.confidence:.0%}")
            lines.append(f"  Classification: {item.classification}")
            lines.append(f"  Paths: {', '.join(item.paths)}")
            lines.append(f"  Why not automatic: {item.why_automatic_cleanup_not_recommended}")
            lines.append(f"  Manual action: {item.exact_manual_action}")
            lines.append(f"  Verify: {item.verification_command}")
            lines.append(f"  Expected: {item.expected_post_condition}")
    return "\n".join(lines)


def _category_for_generation(generation: Generation, regeneration: Any) -> str | None:
    if generation.classification == GenerationClassification.TRASH or generation.trash_registrations:
        return "trash"
    if generation.classification == GenerationClassification.MOUNTED_INSTALLER or generation.mounted_volume_registrations:
        return "mounted_installer"
    if generation.product_family in {"GoogleUpdater", "EdgeUpdater"} or generation.updater_registrations:
        return "updater"
    if generation.product_family == "Google Chrome" and not generation.active:
        return "unknown_chrome_application"
    return None


def _item_for_generation(generation: Generation, category: str, producer: str, regeneration: Any) -> CleanupChecklistItem:
    regenerator = getattr(regeneration, "regenerator", "Unknown") if regeneration is not None else "Unknown"
    confidence = float(getattr(regeneration, "confidence", 0.25)) if regeneration is not None else 0.25
    paths = sorted({registration.path for registration in generation.registrations if registration.path})
    registration_ids = sorted({_registration_id(registration.to_json_dict()) for registration in generation.registrations})
    why, action, expected = _manual_text(category, paths)
    return CleanupChecklistItem(
        item_id=f"{category}:{generation.generation_id}",
        category=category,
        generation_id=generation.generation_id,
        producer=producer,
        regenerator=regenerator,
        confidence=confidence,
        classification=generation.classification.value,
        paths=paths,
        registration_ids=registration_ids,
        why_automatic_cleanup_not_recommended=why,
        exact_manual_action=action,
        verification_command="mse launchservices cleanup-checklist --json",
        expected_post_condition=expected,
    )


def _manual_text(category: str, paths: list[str]) -> tuple[str, str, str]:
    if category == "trash":
        return (
            "Trash contents may include user-disposable files; automatic cleanup is not recommended because emptying Trash is destructive and user-scoped.",
            "Inspect Finder Trash, empty only if contents are disposable, reboot, then verify with mse launchservices cleanup-checklist --json.",
            "Trash generation absent from LaunchServices cleanup checklist and Local Network evidence improves or remains explainable by other categories.",
        )
    if category == "mounted_installer":
        volume = _mounted_volume(paths) or "/Volumes/Google Chrome"
        return (
            "Mounted installer volumes can be active user media; automatic eject is not recommended without user confirmation.",
            f"Eject {volume}, then reboot or relaunch System Settings, then verify with mse launchservices cleanup-checklist --json.",
            f"Mounted installer generation absent and {volume} is no longer contributing LaunchServices registrations.",
        )
    if category == "updater":
        return (
            "Updater-owned paths require manual review or vendor updater cleanup; do not delete blindly because updater components may be active or managed by vendor services.",
            "Review the updater-owned path with Finder/System Settings or the vendor updater, do not delete blindly, then verify with mse launchservices cleanup-checklist --json.",
            "Updater generation is either intentionally present or removed by a vendor-supported cleanup path.",
        )
    return (
        "The Chrome application generation has an unknown regenerator, so automatic cleanup is not recommended until higher-confidence Trash and mounted-installer sources are cleared.",
        "After Trash and mounted installer branches are cleared, perform a manual Chrome reinstall from the official installer, reboot or relaunch System Settings, then verify with mse launchservices cleanup-checklist --json.",
        "Unknown-regenerator Chrome application generation is absent or has a known producer/regenerator after reinstall verification.",
    )


def _mounted_volume(paths: list[str]) -> str | None:
    for path in paths:
        if path.startswith("/Volumes/"):
            parts = path.split("/")
            if len(parts) >= 3:
                return "/".join(parts[:3])
    return None


def _producer_by_generation(analysis: GenerationAnalysis) -> dict[str, str]:
    provenance = build_launchservices_provenance(analysis).to_json_dict()
    result: dict[str, str] = {}
    for item in provenance.get("registrations", []):
        if isinstance(item, dict) and isinstance(item.get("generation_id"), str):
            result.setdefault(item["generation_id"], str(item.get("producer") or "Unknown"))
    return result


def _registration_id(registration: dict[str, Any]) -> str:
    bundle = str(registration.get("bundle_id") or registration.get("name") or "unknown")
    path = str(registration.get("path") or "unknown-path")
    return f"{bundle}:{hashlib.sha256(path.encode()).hexdigest()[:12]}"
