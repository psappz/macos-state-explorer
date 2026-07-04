from __future__ import annotations

from collections import Counter
from typing import Any

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.evidence.models import EvidenceItem, EvidenceSet
from macos_state_explorer.launchservices.models import LaunchServicesStatus


def extract_evidence(snapshot: Snapshot) -> EvidenceSet:
    payloads = {observation.collector: observation.payload for observation in snapshot.observations}
    items: list[EvidenceItem] = []
    items.extend(_launchservices_evidence(payloads.get("launchservices", {})))
    tcc_evidence = _tcc_evidence(payloads.get("tcc", {}))
    if tcc_evidence:
        items.append(tcc_evidence)
    return EvidenceSet(items=items)


def _launchservices_evidence(payload: dict[str, Any]) -> list[EvidenceItem]:
    entries = payload.get("entries", [])
    items: list[EvidenceItem] = []
    orphaned = _entries_with_status(entries, LaunchServicesStatus.ORPHANED)
    missing_volume = _entries_with_status(entries, LaunchServicesStatus.MISSING_VOLUME)
    stale = _entries_with_status(entries, LaunchServicesStatus.STALE)
    duplicate_bundle_ids = _duplicate_bundle_ids(entries)

    if orphaned:
        items.append(
            EvidenceItem(
                id="launchservices.orphaned_registrations",
                title="Orphaned app registrations",
                summary=f"{len(orphaned)} LaunchServices registrations point to app nodes not found on disk.",
                source="launchservices",
                severity="high",
                confidence=0.9,
                data={"count": len(orphaned), "records": _summarize_entries(orphaned)},
            )
        )

    if missing_volume:
        items.append(
            EvidenceItem(
                id="launchservices.missing_volume_registrations",
                title="Missing volume registrations",
                summary=f"{len(missing_volume)} LaunchServices registrations reference missing volumes.",
                source="launchservices",
                severity="medium",
                confidence=0.9,
                data={"count": len(missing_volume), "records": _summarize_entries(missing_volume)},
            )
        )

    if stale:
        items.append(
            EvidenceItem(
                id="launchservices.stale_app_paths",
                title="Stale app paths",
                summary=f"{len(stale)} LaunchServices registrations point to paths that do not currently exist.",
                source="launchservices",
                severity="medium",
                confidence=0.85,
                data={"count": len(stale), "records": _summarize_entries(stale)},
            )
        )

    if duplicate_bundle_ids:
        items.append(
            EvidenceItem(
                id="launchservices.duplicate_bundle_registrations",
                title="Duplicate bundle registrations",
                summary=f"{len(duplicate_bundle_ids)} bundle identifiers have multiple LaunchServices records.",
                source="launchservices",
                severity="medium",
                confidence=0.8,
                data={"bundle_ids": duplicate_bundle_ids},
            )
        )

    return items


def _tcc_evidence(payload: dict[str, Any]) -> EvidenceItem | None:
    if _has_localnetwork_rows(payload):
        return None
    return EvidenceItem(
        id="tcc.no_localnetwork_rows",
        title="TCC has no Local Network rows",
        summary="No kTCCServiceLocalNetwork rows were found in collected TCC data.",
        source="tcc",
        severity="medium",
        confidence=0.9,
        data={"collector": "tcc"},
    )


def _entries_with_status(entries: list[dict[str, Any]], status: LaunchServicesStatus) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("classification") == status.value]


def _duplicate_bundle_ids(entries: list[dict[str, Any]]) -> list[str]:
    counts = Counter(entry.get("bundle_id") for entry in entries if entry.get("bundle_id"))
    return sorted(bundle_id for bundle_id, count in counts.items() if count > 1)


def _summarize_entries(entries: list[dict[str, Any]]) -> list[dict[str, object]]:
    return [
        {
            "bundle_id": entry.get("bundle_id"),
            "identifier": entry.get("identifier"),
            "name": entry.get("display_name") or entry.get("name"),
            "path": entry.get("path_clean") or entry.get("path"),
            "classification": entry.get("classification"),
        }
        for entry in entries
    ]


def _has_localnetwork_rows(payload: dict[str, Any]) -> bool:
    direct = payload.get("direct_localnetwork_query", {})
    stdout = direct.get("stdout", "") if isinstance(direct, dict) else ""
    if stdout.strip():
        return True

    for key in ("user_tcc", "system_tcc", "regdb"):
        overview = payload.get(key, {})
        if isinstance(overview, dict) and _contains_localnetwork(overview.get("hits", [])):
            return True
    return False


def _contains_localnetwork(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_localnetwork(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_localnetwork(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "ktccservicelocalnetwork" in lowered or "localnetwork" in lowered
    return False
