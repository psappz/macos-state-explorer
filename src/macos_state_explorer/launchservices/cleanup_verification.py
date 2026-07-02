from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from macos_state_explorer.launchservices.generations import Generation, GenerationAnalysis, GenerationClassification
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance

BUCKET_ORDER = ["verified", "still_present", "unexpected", "unknown"]
BUCKET_TITLES = {
    "verified": "Verified",
    "still_present": "Still Present",
    "unexpected": "Unexpected",
    "unknown": "Unknown",
}


@dataclass(frozen=True)
class CleanupVerificationItem:
    item_id: str
    bucket: str
    generation_id: str
    producer: str
    previous_classification: str
    current_classification: str
    expected_state: str
    actual_state: str
    explanation: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "generation_id": self.generation_id,
            "producer": self.producer,
            "previous_classification": self.previous_classification,
            "current_classification": self.current_classification,
            "expected_state": self.expected_state,
            "actual_state": self.actual_state,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class LaunchServicesCleanupVerification:
    verification_id: str
    timestamp: str
    verified: list[CleanupVerificationItem]
    still_present: list[CleanupVerificationItem]
    unexpected: list[CleanupVerificationItem]
    unknown: list[CleanupVerificationItem]

    def to_json_dict(self) -> dict[str, Any]:
        summary = cleanup_verification_summary(self)
        return {
            "command": "launchservices verify-cleanup",
            "verification_id": self.verification_id,
            "timestamp": self.timestamp,
            "summary": {
                "verified": summary["verified"],
                "still_present": summary["still_present"],
                "unexpected": summary["unexpected"],
                "unknown": summary["unknown"],
                "active_generations_preserved": summary["active_generations_preserved"],
                "new_stale_generations": summary["new_stale_generations"],
            },
            "verified": [item.to_json_dict() for item in self.verified],
            "still_present": [item.to_json_dict() for item in self.still_present],
            "unexpected": [item.to_json_dict() for item in self.unexpected],
            "unknown": [item.to_json_dict() for item in self.unknown],
            "read_only": True,
            "mutation_performed": False,
        }


def build_launchservices_cleanup_verification(analysis: GenerationAnalysis) -> LaunchServicesCleanupVerification:
    producer_by_id = _producer_by_generation(analysis)
    items: dict[str, list[CleanupVerificationItem]] = {bucket: [] for bucket in BUCKET_ORDER}

    trash_generations = [generation for generation in analysis.generations if _is_trash(generation)]
    mounted_generations = [generation for generation in analysis.generations if _is_mounted_installer(generation)]
    updater_generations = [generation for generation in analysis.generations if _is_updater(generation)]
    unknown_chrome_generations = [generation for generation in analysis.generations if _is_unknown_chrome_application(generation)]
    active_generations = [generation for generation in analysis.generations if generation.active]

    if not trash_generations:
        items["verified"].append(
            _synthetic_item(
                "trash:removed",
                bucket="verified",
                generation_id="trash-registrations",
                previous_classification="trash",
                current_classification="absent",
                expected_state="trash registrations absent",
                actual_state="absent",
                explanation="No Trash LaunchServices generation is present in the current snapshot.",
            )
        )
    else:
        for generation in trash_generations:
            items["still_present"].append(
                _generation_item(
                    generation,
                    producer_by_id,
                    bucket="still_present",
                    previous_classification="trash",
                    expected_state="trash registrations absent",
                    actual_state="present",
                    explanation="Trash registrations are still present after the expected manual cleanup.",
                )
            )

    for generation in mounted_generations:
        bucket = "unexpected" if _is_stale(generation) else "still_present"
        items[bucket].append(
            _generation_item(
                generation,
                producer_by_id,
                bucket=bucket,
                previous_classification="new_stale_generation" if bucket == "unexpected" else "mounted_installer",
                expected_state="mounted installer registrations absent",
                actual_state="present",
                explanation="A mounted installer LaunchServices generation is present in the current snapshot.",
            )
        )

    for generation in updater_generations:
        items["unknown"].append(
            _generation_item(
                generation,
                producer_by_id,
                bucket="unknown",
                previous_classification="updater",
                expected_state="updater registrations intentionally reviewed or vendor-cleaned",
                actual_state="present",
                explanation="Updater ownership cannot be verified from the current snapshot alone; manual review is still required.",
            )
        )

    for generation in unknown_chrome_generations:
        items["still_present"].append(
            _generation_item(
                generation,
                producer_by_id,
                bucket="still_present",
                previous_classification="unknown_chrome_application",
                expected_state="non-automatic cleanup source absent or resolved",
                actual_state="present",
                explanation="An unknown-regenerator Chrome application generation still persists after expected manual cleanup.",
            )
        )

    if active_generations:
        primary_active = sorted(active_generations, key=lambda generation: generation.generation_id)[0]
        items["verified"].append(
            _generation_item(
                primary_active,
                producer_by_id,
                bucket="verified",
                previous_classification="active_generation",
                expected_state="active generation preserved",
                actual_state="present",
                explanation="The active Chrome/Chromium generation is still present and protected.",
            )
        )

    for bucket in BUCKET_ORDER:
        items[bucket].sort(key=_item_sort_key)
    digest_basis = "|".join(
        f"{bucket}:{item.item_id}:{item.actual_state}" for bucket in BUCKET_ORDER for item in items[bucket]
    )
    verification_id = f"ls-cleanup-verification-{hashlib.sha256(digest_basis.encode()).hexdigest()[:12]}"
    return LaunchServicesCleanupVerification(
        verification_id=verification_id,
        timestamp="1970-01-01T00:00:00Z",
        verified=items["verified"],
        still_present=items["still_present"],
        unexpected=items["unexpected"],
        unknown=items["unknown"],
    )


def cleanup_verification_summary(verification: LaunchServicesCleanupVerification) -> dict[str, Any]:
    all_items = verification.verified + verification.still_present + verification.unexpected + verification.unknown
    verified_ids = [item.item_id for item in verification.verified]
    failed_ids = [item.item_id for item in verification.still_present + verification.unexpected]
    newly_appeared = [item.generation_id for item in verification.unexpected]
    disappeared = [item.generation_id for item in verification.verified if item.actual_state == "absent"]
    unchanged = [item.generation_id for item in verification.still_present + verification.unknown if item.actual_state == "present"]
    return {
        "verified": len(verification.verified),
        "still_present": len(verification.still_present),
        "unexpected": len(verification.unexpected),
        "unknown": len(verification.unknown),
        "verified_item_ids": verified_ids,
        "failed_item_ids": failed_ids,
        "newly_appeared_generation_ids": newly_appeared,
        "disappeared_generation_ids": disappeared,
        "unchanged_generation_ids": unchanged,
        "active_generations_preserved": any(item.previous_classification == "active_generation" for item in verification.verified),
        "new_stale_generations": len(newly_appeared),
        "item_ids": [item.item_id for item in all_items],
        "read_only": True,
        "mutation_performed": False,
    }


def local_network_cleanup_verification_summary(verification: LaunchServicesCleanupVerification) -> dict[str, Any]:
    summary = cleanup_verification_summary(verification)
    return {
        "verified": summary["verified"],
        "still_present": summary["still_present"],
        "unexpected": summary["unexpected"],
        "unknown": summary["unknown"],
        "verified_item_ids": summary["verified_item_ids"],
        "failed_item_ids": summary["failed_item_ids"],
        "newly_appeared_generation_ids": summary["newly_appeared_generation_ids"],
        "disappeared_generation_ids": summary["disappeared_generation_ids"],
        "unchanged_generation_ids": summary["unchanged_generation_ids"],
        "read_only": True,
        "mutation_performed": False,
    }


def render_cleanup_verification_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "LaunchServices cleanup verification",
            f"- Verified: {summary.get('verified', 0)}",
            f"- Still present: {summary.get('still_present', 0)}",
            f"- Unexpected: {summary.get('unexpected', 0)}",
            f"- Unknown: {summary.get('unknown', 0)}",
        ]
    )


def render_launchservices_cleanup_verification(verification: LaunchServicesCleanupVerification) -> str:
    lines = ["LaunchServices cleanup verification", "No mutation is performed. This command verifies manual cleanup effects only."]
    for bucket in BUCKET_ORDER:
        title = BUCKET_TITLES[bucket]
        lines.extend(["", title])
        bucket_items = getattr(verification, bucket)
        if not bucket_items:
            lines.append("- none")
            continue
        for item in bucket_items:
            lines.append(f"- {item.generation_id}")
            lines.append(f"  Producer: {item.producer}")
            lines.append(f"  Previous classification: {item.previous_classification}")
            lines.append(f"  Current classification: {item.current_classification}")
            lines.append(f"  Expected: {item.expected_state}")
            lines.append(f"  Actual: {item.actual_state}")
            lines.append(f"  Explanation: {item.explanation}")
    return "\n".join(lines)


def _item_sort_key(item: CleanupVerificationItem) -> tuple[int, str]:
    priority = {
        "trash": 0,
        "mounted_installer": 1,
        "unknown_chrome_application": 2,
        "updater": 3,
        "new_stale_generation": 4,
        "active_generation": 5,
    }
    return (priority.get(item.previous_classification, 9), item.item_id)


def _generation_item(
    generation: Generation,
    producer_by_id: dict[str, str],
    *,
    bucket: str,
    previous_classification: str,
    expected_state: str,
    actual_state: str,
    explanation: str,
) -> CleanupVerificationItem:
    return CleanupVerificationItem(
        item_id=f"{previous_classification}:{generation.generation_id}",
        bucket=bucket,
        generation_id=generation.generation_id,
        producer=producer_by_id.get(generation.generation_id, "Unknown"),
        previous_classification=previous_classification,
        current_classification=generation.classification.value,
        expected_state=expected_state,
        actual_state=actual_state,
        explanation=explanation,
    )


def _synthetic_item(
    item_id: str,
    *,
    bucket: str,
    generation_id: str,
    previous_classification: str,
    current_classification: str,
    expected_state: str,
    actual_state: str,
    explanation: str,
) -> CleanupVerificationItem:
    return CleanupVerificationItem(
        item_id=item_id,
        bucket=bucket,
        generation_id=generation_id,
        producer="Unknown",
        previous_classification=previous_classification,
        current_classification=current_classification,
        expected_state=expected_state,
        actual_state=actual_state,
        explanation=explanation,
    )


def _producer_by_generation(analysis: GenerationAnalysis) -> dict[str, str]:
    provenance = build_launchservices_provenance(analysis).to_json_dict()
    result: dict[str, str] = {}
    for item in provenance.get("registrations", []):
        if isinstance(item, dict) and isinstance(item.get("generation_id"), str):
            result.setdefault(item["generation_id"], str(item.get("producer") or "Unknown"))
    return result


def _is_trash(generation: Generation) -> bool:
    return generation.classification == GenerationClassification.TRASH or bool(generation.trash_registrations)


def _is_mounted_installer(generation: Generation) -> bool:
    return generation.classification == GenerationClassification.MOUNTED_INSTALLER or bool(generation.mounted_volume_registrations)


def _is_updater(generation: Generation) -> bool:
    return generation.product_family in {"GoogleUpdater", "EdgeUpdater"} or bool(generation.updater_registrations)


def _is_unknown_chrome_application(generation: Generation) -> bool:
    return generation.product_family == "Google Chrome" and not generation.active and not _is_trash(generation) and not _is_mounted_installer(generation)


def _is_stale(generation: Generation) -> bool:
    return generation.stale or generation.classification in {
        GenerationClassification.MOUNTED_INSTALLER,
        GenerationClassification.STALE,
        GenerationClassification.MISSING,
        GenerationClassification.TRASH,
        GenerationClassification.PARTIAL,
        GenerationClassification.UNKNOWN,
    }
