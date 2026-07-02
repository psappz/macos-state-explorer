from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from macos_state_explorer.launchservices.generations import analyze_generations, generation_summary, render_generation_summary
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


class LaunchServicesRootCause(StrEnum):
    HEALTHY = "Healthy"
    TRASH_APPLICATION = "Trash application"
    MISSING_APPLICATION_BUNDLE = "Missing application bundle"
    MOUNTED_INSTALLER_DMG = "Mounted installer DMG"
    OLD_CHROME_VERSION = "Old Chrome version"
    OLD_FRAMEWORK_VERSION = "Old framework version"
    OLD_HELPER_APPLICATION = "Old helper application"
    DUPLICATE_BUNDLE_REGISTRATION = "Duplicate bundle registration"
    NONEXISTENT_VOLUME = "Nonexistent volume"
    INVALID_BUNDLE = "Invalid bundle"
    UNKNOWN = "Unknown"


class LaunchServicesRepairability(StrEnum):
    SAFE_AUTOMATIC = "SAFE_AUTOMATIC"
    SAFE_MANUAL = "SAFE_MANUAL"
    REQUIRES_REINSTALL = "REQUIRES_REINSTALL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LaunchServicesAnalysisEntry:
    path: str | None
    bundle_id: str | None
    bundle_name: str | None
    version: str | None
    executable: str | None
    exists_on_disk: bool | None
    registration_source: str
    registration_type: str
    evidence: list[str]
    root_cause: LaunchServicesRootCause
    repairability: LaunchServicesRepairability
    confidence: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bundle_id": self.bundle_id,
            "bundle_name": self.bundle_name,
            "version": self.version,
            "executable": self.executable,
            "exists_on_disk": self.exists_on_disk,
            "registration_source": self.registration_source,
            "registration_type": self.registration_type,
            "evidence": list(self.evidence),
            "root_cause": self.root_cause.value,
            "repairability": self.repairability.value,
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True)
class LaunchServicesAnalysisGroup:
    root_cause: LaunchServicesRootCause
    count: int
    confidence: float
    explanation: str
    suggested_repair: str
    safety: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause.value,
            "count": self.count,
            "confidence": round(self.confidence, 4),
            "explanation": self.explanation,
            "suggested_repair": self.suggested_repair,
            "safety": self.safety,
        }


@dataclass(frozen=True)
class LaunchServicesAnalysis:
    entries: list[LaunchServicesAnalysisEntry]
    groups: list[LaunchServicesAnalysisGroup]
    generations: Any | None = None

    def to_json_dict(self) -> dict[str, Any]:
        payload = {
            "command": "launchservices analyze",
            "entry_count": len(self.entries),
            "groups": [group.to_json_dict() for group in self.groups],
            "entries": [entry.to_json_dict() for entry in self.entries],
        }
        if self.generations is not None:
            payload["generation_summary"] = generation_summary(self.generations)
        return payload


def analyze_launchservices(records: Iterable[LaunchServicesRecord | dict[str, Any]]) -> LaunchServicesAnalysis:
    normalized = [_record_from_value(record) for record in records]
    latest_versions = _latest_versions_by_bundle(normalized)
    entries = [_analyze_record(record, latest_versions) for record in normalized]
    entries.sort(key=lambda entry: (entry.root_cause.value, entry.path or "", entry.bundle_id or ""))
    groups = _build_groups(entries)
    generations = analyze_generations(normalized)
    return LaunchServicesAnalysis(entries=entries, groups=groups, generations=generations)


def render_launchservices_analysis(analysis: LaunchServicesAnalysis, *, verbose: bool = False) -> str:
    lines = ["LaunchServices root cause analysis", "", "Root causes"]
    if not analysis.groups:
        lines.append("- No LaunchServices registrations to analyze.")
    for group in analysis.groups:
        noun = "registration" if group.count == 1 else "registrations"
        lines.extend(
            [
                "",
                group.root_cause.value,
                "-" * len(group.root_cause.value),
                f"{group.count} {noun}",
                f"Confidence: {group.confidence:.0%}",
                f"Explanation: {group.explanation}",
                f"Suggested repair: {group.suggested_repair}",
                f"Safety: {group.safety}",
            ]
        )
    entries = analysis.entries if verbose else [entry for entry in analysis.entries if entry.root_cause != LaunchServicesRootCause.HEALTHY]
    if analysis.generations is not None:
        lines.extend(["", "Generation summary", "==================", "", render_generation_summary(analysis.generations)])
    lines.extend(["", "Per-entry analysis"])
    if not entries:
        lines.append("- No suspicious LaunchServices registrations detected. Use --verbose to show healthy entries.")
    for entry in entries:
        exists = "exists" if entry.exists_on_disk is True else "missing" if entry.exists_on_disk is False else "unknown"
        lines.extend(
            [
                f"- {entry.path or '<missing path>'}",
                f"  Exists: {exists}",
                f"  Bundle ID: {entry.bundle_id or '<missing>'}",
                f"  Version: {entry.version or '<missing>'}",
                f"  Group: {entry.root_cause.value}",
                f"  Confidence: {entry.confidence:.0%}",
                f"  Repairability: {entry.repairability.value}",
                f"  Reasoning: {'; '.join(entry.evidence) if entry.evidence else 'No deterministic reasoning available.'}",
            ]
        )
    return "\n".join(lines)


def analysis_records_from_snapshot_payload(payload: dict[str, Any]) -> list[LaunchServicesRecord]:
    raw = payload.get("entries") or payload.get("stale_entries") or []
    return [_record_from_value(item) for item in raw if isinstance(item, dict) or isinstance(item, LaunchServicesRecord)]


def analysis_from_snapshot_payload(payload: dict[str, Any]) -> LaunchServicesAnalysis:
    return analyze_launchservices(analysis_records_from_snapshot_payload(payload))


def summarize_root_causes(analysis: LaunchServicesAnalysis) -> str:
    if not analysis.groups:
        return "Root causes: none classified."
    parts = ["Root causes"]
    for group in analysis.groups:
        label = _summary_label(group.root_cause, group.count)
        parts.append(f"• {group.count} {label}")
    return "\n".join(parts)


def _record_from_value(value: LaunchServicesRecord | dict[str, Any]) -> LaunchServicesRecord:
    if isinstance(value, LaunchServicesRecord):
        return value
    data = dict(value)
    data.setdefault("raw_block", str(value))
    return LaunchServicesRecord(**data)


def _latest_versions_by_bundle(records: list[LaunchServicesRecord]) -> dict[str, str]:
    latest: dict[str, str] = {}
    for record in records:
        if not record.bundle_id or not record.version:
            continue
        current = latest.get(record.bundle_id)
        if current is None or _version_key(record.version) > _version_key(current):
            latest[record.bundle_id] = record.version
    return latest


def _analyze_record(
    record: LaunchServicesRecord,
    latest_versions: dict[str, str],
) -> LaunchServicesAnalysisEntry:
    path = record.path_clean or record.path
    path_lower = (path or "").lower()
    bundle_lower = (record.bundle_id or "").lower()
    name_lower = (record.display_name or record.name or "").lower()
    evidence: list[str] = []

    if "/.trash/" in path_lower or path_lower.startswith("/users/") and "/trash/" in path_lower:
        root = LaunchServicesRootCause.TRASH_APPLICATION
        repairability = LaunchServicesRepairability.SAFE_MANUAL
        confidence = 0.96
        evidence.append("Bundle resides inside ~/.Trash.")
    elif record.volume and record.volume.startswith("/Volumes/") and record.volume_exists is False:
        root = LaunchServicesRootCause.NONEXISTENT_VOLUME
        repairability = LaunchServicesRepairability.UNKNOWN
        confidence = 0.94
        evidence.append("Registration references a volume that is not mounted.")
    elif path_lower.startswith("/volumes/") and record.volume_exists is True:
        root = LaunchServicesRootCause.MOUNTED_INSTALLER_DMG
        repairability = LaunchServicesRepairability.SAFE_MANUAL
        confidence = 0.9
        evidence.append("Registration references a mounted installer volume.")
    elif _is_chrome_helper_or_updater(path_lower, bundle_lower, name_lower):
        root = LaunchServicesRootCause.OLD_HELPER_APPLICATION
        repairability = LaunchServicesRepairability.SAFE_MANUAL
        confidence = 0.86
        evidence.append("Registration points at a Chrome/Google/Edge helper or updater application.")
    elif _is_google_chrome_framework(path_lower, bundle_lower, name_lower):
        latest = latest_versions.get(record.bundle_id or "")
        if latest and record.version == latest and record.path_exists is True:
            root = LaunchServicesRootCause.HEALTHY
            repairability = LaunchServicesRepairability.SAFE_AUTOMATIC
            confidence = 0.99
            evidence.append("Framework registration appears to match the newest active Chrome Framework version.")
        else:
            root = LaunchServicesRootCause.OLD_FRAMEWORK_VERSION
            repairability = LaunchServicesRepairability.SAFE_MANUAL
            confidence = 0.88 if latest and record.version != latest else 0.78
            evidence.append(f"Google Chrome Framework version differs from installed Chrome Framework version {latest}.")
    elif record.classification == LaunchServicesStatus.DUPLICATE:
        root = LaunchServicesRootCause.DUPLICATE_BUNDLE_REGISTRATION
        repairability = LaunchServicesRepairability.SAFE_MANUAL
        confidence = 0.85
        evidence.append("Bundle identifier duplicates an active registration.")
    elif _looks_invalid_bundle(path, record):
        root = LaunchServicesRootCause.INVALID_BUNDLE
        repairability = LaunchServicesRepairability.UNKNOWN
        confidence = 0.8
        evidence.append("Registration does not describe a valid application or framework bundle.")
    elif _is_old_chrome(record, latest_versions):
        root = LaunchServicesRootCause.OLD_CHROME_VERSION
        repairability = LaunchServicesRepairability.REQUIRES_REINSTALL
        confidence = 0.84
        evidence.append("Chrome version differs from the newest registered Chrome version.")
    elif record.path_exists is False or record.node_not_found or record.classification in {LaunchServicesStatus.STALE, LaunchServicesStatus.ORPHANED}:
        root = LaunchServicesRootCause.MISSING_APPLICATION_BUNDLE
        repairability = LaunchServicesRepairability.REQUIRES_REINSTALL
        confidence = 0.9
        evidence.append("Referenced bundle path no longer exists.")
    elif record.path_exists is True and record.classification == LaunchServicesStatus.ACTIVE:
        root = LaunchServicesRootCause.HEALTHY
        repairability = LaunchServicesRepairability.SAFE_AUTOMATIC
        confidence = 0.99
        evidence.append("Registration points at an existing active bundle and is not suspicious.")
    else:
        root = LaunchServicesRootCause.UNKNOWN
        repairability = LaunchServicesRepairability.UNKNOWN
        confidence = 0.5
        evidence.append("No deterministic LaunchServices root-cause classifier matched this registration.")

    return LaunchServicesAnalysisEntry(
        path=path,
        bundle_id=record.bundle_id or record.identifier or record.canonical_id,
        bundle_name=record.display_name or record.name,
        version=record.display_version or record.version,
        executable=record.executable,
        exists_on_disk=record.path_exists,
        registration_source=record.volume or "unknown",
        registration_type=str(record.classification.value if hasattr(record.classification, "value") else record.classification),
        evidence=evidence,
        root_cause=root,
        repairability=repairability,
        confidence=confidence,
    )


def _build_groups(entries: list[LaunchServicesAnalysisEntry]) -> list[LaunchServicesAnalysisGroup]:
    counts = Counter(entry.root_cause for entry in entries if entry.root_cause != LaunchServicesRootCause.HEALTHY)
    groups: list[LaunchServicesAnalysisGroup] = []
    for root_cause, count in counts.items():
        root_entries = [entry for entry in entries if entry.root_cause == root_cause]
        groups.append(
            LaunchServicesAnalysisGroup(
                root_cause=root_cause,
                count=count,
                confidence=sum(entry.confidence for entry in root_entries) / count,
                explanation=_group_explanation(root_cause),
                suggested_repair=_group_repair(root_cause),
                safety=_group_safety(root_cause),
            )
        )
    groups.sort(key=lambda group: (group.root_cause == LaunchServicesRootCause.UNKNOWN, -group.count, group.root_cause.value))
    return groups


def _is_old_chrome(record: LaunchServicesRecord, latest_versions: dict[str, str]) -> bool:
    if record.bundle_id != "com.google.Chrome" or not record.version:
        return False
    latest = latest_versions.get(record.bundle_id)
    return bool(latest and _version_key(record.version) < _version_key(latest))


def _is_google_chrome_framework(path_lower: str, bundle_lower: str, name_lower: str) -> bool:
    return (
        "google chrome framework.framework" in path_lower
        or bundle_lower == "com.google.chrome.framework"
        or name_lower == "google chrome framework"
    )


def _is_chrome_helper_or_updater(path_lower: str, bundle_lower: str, name_lower: str) -> bool:
    haystack = " ".join((path_lower, bundle_lower, name_lower))
    return (
        ("google chrome" in haystack and "helper" in haystack)
        or "googleupdater" in haystack
        or "google updater" in haystack
        or "edgeupdater" in haystack
        or "edge updater" in haystack
    )


def _looks_invalid_bundle(path: str | None, record: LaunchServicesRecord) -> bool:
    if not path or record.path_exists is None:
        return False
    lower = path.lower()
    return record.executable is None and not any(suffix in lower for suffix in (".app", ".framework", ".appex"))


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.replace("-", ".").split("."):
        if part.isdecimal():
            parts.append(int(part))
        else:
            break
    return tuple(parts)


def _group_explanation(root: LaunchServicesRootCause) -> str:
    return {
        LaunchServicesRootCause.HEALTHY: "Registration points at an existing active bundle and is not suspicious.",
        LaunchServicesRootCause.TRASH_APPLICATION: "Registration path is inside the user's Trash.",
        LaunchServicesRootCause.MISSING_APPLICATION_BUNDLE: "LaunchServices references an application bundle path that no longer exists.",
        LaunchServicesRootCause.MOUNTED_INSTALLER_DMG: "Registration path is under /Volumes while the volume is currently mounted.",
        LaunchServicesRootCause.OLD_CHROME_VERSION: "Chrome bundle version is older than the newest registered Chrome version.",
        LaunchServicesRootCause.OLD_FRAMEWORK_VERSION: "Chrome Framework registration points at an older framework version.",
        LaunchServicesRootCause.OLD_HELPER_APPLICATION: "Registration belongs to a Chrome helper application rather than the main app.",
        LaunchServicesRootCause.DUPLICATE_BUNDLE_REGISTRATION: "Bundle identifier duplicates another active registration.",
        LaunchServicesRootCause.NONEXISTENT_VOLUME: "Registration path is under a /Volumes mount point that is not present.",
        LaunchServicesRootCause.INVALID_BUNDLE: "Registration lacks enough bundle structure to be a valid app/framework registration.",
        LaunchServicesRootCause.UNKNOWN: "No deterministic classifier matched the registration.",
    }[root]


def _group_repair(root: LaunchServicesRootCause) -> str:
    return {
        LaunchServicesRootCause.HEALTHY: "No repair needed.",
        LaunchServicesRootCause.TRASH_APPLICATION: "Review Trash manually, empty only disposable app leftovers, then reboot and re-check.",
        LaunchServicesRootCause.MISSING_APPLICATION_BUNDLE: "Reinstall the missing application or inspect stale LaunchServices paths before cleanup.",
        LaunchServicesRootCause.MOUNTED_INSTALLER_DMG: "Unmount installer volumes after installation, then re-check LaunchServices.",
        LaunchServicesRootCause.OLD_CHROME_VERSION: "Install the current Chrome release into /Applications and re-check registrations.",
        LaunchServicesRootCause.OLD_FRAMEWORK_VERSION: "Prefer manual Chrome reinstall; do not delete framework paths automatically.",
        LaunchServicesRootCause.OLD_HELPER_APPLICATION: "Prefer manual Chrome reinstall; do not delete helper paths automatically.",
        LaunchServicesRootCause.DUPLICATE_BUNDLE_REGISTRATION: "Compare active path/version pairs before choosing a manual reinstall or ignore decision.",
        LaunchServicesRootCause.NONEXISTENT_VOLUME: "Inspect whether the volume should be remounted or the app reinstalled.",
        LaunchServicesRootCause.INVALID_BUNDLE: "Collect a support bundle and inspect the raw registration before any action.",
        LaunchServicesRootCause.UNKNOWN: "Collect a support bundle for manual inspection.",
    }[root]


def _group_safety(root: LaunchServicesRootCause) -> str:
    return {
        LaunchServicesRootCause.HEALTHY: "SAFE_AUTOMATIC",
        LaunchServicesRootCause.TRASH_APPLICATION: "SAFE_MANUAL",
        LaunchServicesRootCause.MISSING_APPLICATION_BUNDLE: "REQUIRES_REINSTALL",
        LaunchServicesRootCause.MOUNTED_INSTALLER_DMG: "SAFE_MANUAL",
        LaunchServicesRootCause.OLD_CHROME_VERSION: "REQUIRES_REINSTALL",
        LaunchServicesRootCause.OLD_FRAMEWORK_VERSION: "SAFE_MANUAL",
        LaunchServicesRootCause.OLD_HELPER_APPLICATION: "SAFE_MANUAL",
        LaunchServicesRootCause.DUPLICATE_BUNDLE_REGISTRATION: "SAFE_MANUAL",
        LaunchServicesRootCause.NONEXISTENT_VOLUME: "UNKNOWN",
        LaunchServicesRootCause.INVALID_BUNDLE: "UNKNOWN",
        LaunchServicesRootCause.UNKNOWN: "UNKNOWN",
    }[root]


def _summary_label(root: LaunchServicesRootCause, count: int) -> str:
    plural = count != 1
    return {
        LaunchServicesRootCause.OLD_FRAMEWORK_VERSION: "obsolete Chrome Framework registrations" if plural else "obsolete Chrome Framework registration",
        LaunchServicesRootCause.MOUNTED_INSTALLER_DMG: "stale installer registrations" if plural else "stale installer registration",
        LaunchServicesRootCause.OLD_HELPER_APPLICATION: "obsolete helper registrations" if plural else "obsolete helper registration",
        LaunchServicesRootCause.TRASH_APPLICATION: "Trash registrations" if plural else "Trash registration",
        LaunchServicesRootCause.UNKNOWN: "unknown registrations" if plural else "unknown registration",
    }.get(root, f"{root.value.lower()} registrations" if plural else f"{root.value.lower()} registration")
