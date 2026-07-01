from __future__ import annotations

from collections import Counter
from typing import Any

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticEvidence

STALE_CLASSIFICATIONS = {"STALE", "ORPHANED", "MISSING_VOLUME", "BROKEN"}
SUSPICIOUS_CANDIDATE_TERMS = (".csstore", "launchservices", "lsd")


def collect_launchservices_evidence(snapshot: Snapshot, context: dict[str, Any] | None = None) -> list[DiagnosticEvidence]:
    payload = _launchservices_payload(snapshot)
    entries = list(payload.get("entries", []))
    stale_entries = list(payload.get("stale_entries", [])) or [
        entry for entry in entries if _classification(entry) in STALE_CLASSIFICATIONS
    ]
    missing_path_entries = [entry for entry in entries if _missing_path(entry)]
    duplicate_bundle_ids = _duplicate_bundle_ids(entries)
    suspicious_candidates = _suspicious_candidate_paths(payload)

    return [
        DiagnosticEvidence(
            id="LS-E001",
            title="Stale LaunchServices registrations",
            detail=f"Found {len(stale_entries)} stale, orphaned, missing-volume, or broken registration(s).",
            source="launchservices",
            present=bool(stale_entries),
            confidence=0.9 if stale_entries else 0.2,
            provenance=_entry_labels(stale_entries),
        ),
        DiagnosticEvidence(
            id="LS-E002",
            title="Missing app paths",
            detail=f"Found {len(missing_path_entries)} registration(s) pointing at missing app paths.",
            source="launchservices",
            present=bool(missing_path_entries),
            confidence=0.9 if missing_path_entries else 0.2,
            provenance=_entry_labels(missing_path_entries),
        ),
        DiagnosticEvidence(
            id="LS-E003",
            title="Duplicate bundle identifiers",
            detail=f"Found {len(duplicate_bundle_ids)} bundle identifier(s) with multiple registrations.",
            source="launchservices",
            present=bool(duplicate_bundle_ids),
            confidence=0.85 if duplicate_bundle_ids else 0.2,
            provenance=duplicate_bundle_ids,
        ),
        DiagnosticEvidence(
            id="LS-E004",
            title="Suspicious LaunchServices candidates",
            detail=f"Found {len(suspicious_candidates)} LaunchServices cache or candidate file path(s).",
            source="launchservices",
            present=bool(suspicious_candidates),
            confidence=0.7 if suspicious_candidates else 0.2,
            provenance=suspicious_candidates[:10],
        ),
    ]


def _launchservices_payload(snapshot: Snapshot) -> dict[str, Any]:
    for observation in snapshot.observations:
        if observation.collector == "launchservices":
            return observation.payload
    return {}


def _classification(entry: dict[str, Any]) -> str:
    value = entry.get("classification", "UNKNOWN")
    return str(value.value if hasattr(value, "value") else value)


def _missing_path(entry: dict[str, Any]) -> bool:
    if entry.get("node_not_found") is True:
        return True
    if entry.get("path_exists") is False:
        return True
    return _classification(entry) in {"ORPHANED", "MISSING_VOLUME", "BROKEN"}


def _duplicate_bundle_ids(entries: list[dict[str, Any]]) -> list[str]:
    counts = Counter(str(entry.get("bundle_id")) for entry in entries if entry.get("bundle_id"))
    return sorted(bundle_id for bundle_id, count in counts.items() if count > 1)


def _suspicious_candidate_paths(payload: dict[str, Any]) -> list[str]:
    stdout = str(payload.get("candidate_files", {}).get("stdout", ""))
    paths = [line.strip() for line in stdout.splitlines() if line.strip()]
    return sorted(
        path
        for path in paths
        if any(term in path.lower() for term in SUSPICIOUS_CANDIDATE_TERMS)
    )


def _entry_labels(entries: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for entry in entries:
        label = str(entry.get("bundle_id") or entry.get("display_name") or entry.get("path") or "unknown")
        path = entry.get("path_clean") or entry.get("path")
        if path:
            label = f"{label} @ {path}"
        if label not in labels:
            labels.append(label)
    return labels
