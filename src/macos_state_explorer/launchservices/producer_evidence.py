from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Sequence

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.launchservices.analysis import analysis_records_from_snapshot_payload
from macos_state_explorer.launchservices.generations import GenerationAnalysis, GenerationClassification, GenerationRegistration, analyze_generations

EVIDENCE_TYPES = {
    "lsregister_dump_contains_path",
    "lsregister_dump_contains_bundle_id",
    "csstore_candidate_contains_path",
    "registration_path_exists",
    "registration_path_missing",
    "mounted_volume_path",
    "trash_path",
    "updater_path",
    "active_application_bundle_path",
    "security_privacy_trace_reads_csstore",
    "system_settings_trace_observed",
    "runningboard_trace_observed",
    "spotlight_metadata_present",
    "finder_visible_path",
    "unknown",
}


@dataclass(frozen=True)
class LaunchServicesProducerEvidenceItem:
    evidence_id: str
    target_registration_id: str
    generation_id: str
    path: str | None
    evidence_type: str
    observed: bool
    source: str
    confidence: float
    reasoning: str
    raw_reference: Any
    category: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "target_registration_id": self.target_registration_id,
            "generation_id": self.generation_id,
            "path": self.path,
            "evidence_type": self.evidence_type,
            "observed": self.observed,
            "source": self.source,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "raw_reference": self.raw_reference,
            "category": self.category,
        }


@dataclass(frozen=True)
class LaunchServicesProducerEvidence:
    evidence_id: str
    timestamp: str
    evidence: list[LaunchServicesProducerEvidenceItem]
    trace_context: dict[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        evidence_payload = [item.to_json_dict() for item in self.evidence]
        return {
            "command": "launchservices producer-evidence",
            "evidence_id": self.evidence_id,
            "timestamp": self.timestamp,
            "target_registration_count": len({item.target_registration_id for item in self.evidence}),
            "evidence_count": len(self.evidence),
            "trace_context": dict(self.trace_context),
            "summary": producer_evidence_summary(self),
            "evidence": evidence_payload,
        }


def build_launchservices_producer_evidence(
    snapshot_or_analysis: Snapshot | GenerationAnalysis,
    *,
    trace_analysis: dict[str, Any] | None = None,
    trace_source: Path | str | None = None,
) -> LaunchServicesProducerEvidence:
    analysis = _analysis_from_input(snapshot_or_analysis)
    trace_context = {"available": trace_analysis is not None, "source": str(trace_source) if trace_source is not None else None}
    items: list[LaunchServicesProducerEvidenceItem] = []
    candidate_files = _candidate_files_from_snapshot(snapshot_or_analysis)
    for generation in analysis.generations:
        for registration in generation.registrations:
            items.extend(_snapshot_evidence(generation.classification, registration, candidate_files))
            items.extend(_trace_evidence(registration, trace_analysis))
            items.extend(_inferred_evidence(registration))
    items.sort(key=lambda item: (item.generation_id, item.path or "", item.evidence_type, item.evidence_id))
    digest_basis = "|".join(f"{item.target_registration_id}:{item.evidence_type}:{item.observed}:{item.confidence}" for item in items)
    evidence_id = f"ls-producer-evidence-{hashlib.sha256(digest_basis.encode()).hexdigest()[:12]}"
    return LaunchServicesProducerEvidence(evidence_id=evidence_id, timestamp="1970-01-01T00:00:00Z", evidence=items, trace_context=trace_context)


def producer_evidence_summary(producer_evidence: LaunchServicesProducerEvidence) -> dict[str, Any]:
    observed_items = [item for item in producer_evidence.evidence if item.observed]
    inferred_items = [item for item in producer_evidence.evidence if item.category == "inferred"]
    unknown_items = [item for item in producer_evidence.evidence if item.category == "unknown"]
    type_counts = Counter(item.evidence_type for item in producer_evidence.evidence)
    confidence_by_id = {item.evidence_id: round(item.confidence, 4) for item in producer_evidence.evidence}
    observed_by_id = {item.evidence_id: item.observed for item in producer_evidence.evidence}
    observed_ids = sorted(item.evidence_id for item in observed_items)
    trace_observed = _trace_observed_labels(producer_evidence.evidence)
    return {
        "evidence_count": len(producer_evidence.evidence),
        "observed_evidence_count": len(observed_items),
        "inferred_evidence_count": len(inferred_items),
        "unknown_evidence_count": len(unknown_items),
        "trace_available": bool(producer_evidence.trace_context.get("available")),
        "observed": _observed_summary_lines(producer_evidence.evidence),
        "trace_observed": trace_observed if trace_observed else ["not available"],
        "consumer_evidence": _consumer_evidence_summary_lines(producer_evidence.evidence),
        "inferred": _inferred_summary_lines(producer_evidence.evidence),
        "unknown": _unknown_summary_lines(producer_evidence.evidence),
        "evidence_types": dict(sorted(type_counts.items())),
        "observed_evidence_ids": observed_ids,
        "evidence_confidence": confidence_by_id,
        "observed_status": observed_by_id,
    }


def local_network_producer_evidence_summary(producer_evidence: LaunchServicesProducerEvidence) -> dict[str, Any]:
    summary = producer_evidence_summary(producer_evidence)
    return {
        "observed": summary["observed"],
        "trace_observed": summary["trace_observed"],
        "consumer_evidence": summary["consumer_evidence"],
        "inferred": summary["inferred"],
        "unknown": summary["unknown"],
        "observed_evidence_count": summary["observed_evidence_count"],
        "inferred_evidence_count": summary["inferred_evidence_count"],
        "unknown_evidence_count": summary["unknown_evidence_count"],
        "observed_evidence_ids": summary["observed_evidence_ids"],
        "evidence_confidence": summary["evidence_confidence"],
        "observed_status": summary["observed_status"],
    }


def render_producer_evidence_summary(summary: dict[str, Any]) -> str:
    lines = ["LaunchServices producer evidence", "Observed:"]
    for line in summary.get("observed", []) or ["none"]:
        lines.append(f"- {line}")
    lines.append("Trace observed:")
    for line in summary.get("trace_observed", []) or ["not available"]:
        lines.append(f"- {line}")
    lines.append("Consumer evidence:")
    for line in summary.get("consumer_evidence", []) or ["none"]:
        lines.append(f"- {line}")
    lines.append("Inferred:")
    for line in summary.get("inferred", []) or ["none"]:
        lines.append(f"- {line}")
    if summary.get("unknown"):
        lines.append("Unknown:")
        for line in summary.get("unknown", []):
            lines.append(f"- {line}")
    return "\n".join(lines)


def render_launchservices_producer_evidence(producer_evidence: LaunchServicesProducerEvidence) -> str:
    payload = producer_evidence.to_json_dict()
    lines = ["LaunchServices producer evidence", ""]
    lines.append(f"Trace context: {'available' if payload['trace_context']['available'] else 'unavailable'}")
    lines.extend(["", "Observed evidence"])
    for line in payload["summary"].get("observed", []) or ["none"]:
        lines.append(f"- {line}")
    lines.extend(["", "Trace observed"])
    for line in payload["summary"].get("trace_observed", []) or ["not available"]:
        lines.append(f"- {line}")
    lines.extend(["", "Consumer evidence"])
    for line in payload["summary"].get("consumer_evidence", []) or ["none"]:
        lines.append(f"- {line}")
    lines.extend(["", "Inferred evidence"])
    for line in payload["summary"].get("inferred", []) or ["none"]:
        lines.append(f"- {line}")
    lines.extend(["", "Unknown"])
    for line in payload["summary"].get("unknown", []) or ["none"]:
        lines.append(f"- {line}")
    lines.extend(["", "Evidence records"])
    for item in payload["evidence"]:
        state = "observed" if item["observed"] else "not observed"
        lines.append(f"- {item['evidence_id']} {item['evidence_type']} [{state}, {item['confidence']:.0%}] {item['path'] or '<unknown>'}")
        lines.append(f"  Source: {item['source']}; {item['reasoning']}")
    return "\n".join(lines)


def _analysis_from_input(value: Snapshot | GenerationAnalysis) -> GenerationAnalysis:
    if isinstance(value, GenerationAnalysis):
        return value
    payload = next((observation.payload for observation in value.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return analyze_generations(analysis_records_from_snapshot_payload(payload))


def _candidate_files_from_snapshot(value: Snapshot | GenerationAnalysis) -> str:
    if isinstance(value, GenerationAnalysis):
        return ""
    payload = next((observation.payload for observation in value.observations if observation.collector == "launchservices"), {})
    if not isinstance(payload, dict):
        return ""
    candidate_files = payload.get("candidate_files")
    if isinstance(candidate_files, dict):
        return str(candidate_files.get("stdout", ""))
    return str(candidate_files or "")


def _snapshot_evidence(classification: GenerationClassification, registration: GenerationRegistration, candidate_files: str) -> list[LaunchServicesProducerEvidenceItem]:
    items = [
        _item(registration, "lsregister_dump_contains_path", bool(registration.path), "snapshot", 0.92, "Observed evidence: LaunchServices registration dump includes this path.", registration.path, "observed"),
        _item(registration, "lsregister_dump_contains_bundle_id", bool(registration.bundle_id), "snapshot", 0.9, "Observed evidence: LaunchServices registration dump includes this bundle identifier.", registration.bundle_id, "observed"),
    ]
    if candidate_files and ".csstore" in candidate_files.lower():
        items.append(_item(registration, "csstore_candidate_contains_path", True, "snapshot", 0.78, "Observed evidence: snapshot captured LaunchServices .csstore candidate files.", candidate_files, "observed"))
    if registration.exists_on_disk is True:
        items.append(_item(registration, "registration_path_exists", True, "snapshot", 0.95, "Observed evidence: registered path exists on disk in the snapshot.", registration.path, "observed"))
    if registration.exists_on_disk is False:
        items.append(_item(registration, "registration_path_missing", True, "snapshot", 0.95, "Observed evidence: registered path is missing on disk in the snapshot.", registration.path, "observed"))
    path = registration.path or ""
    if path.startswith("/Volumes/") or classification == GenerationClassification.MOUNTED_INSTALLER:
        items.append(_item(registration, "mounted_volume_path", True, "snapshot", 0.95, "Observed evidence: registration path points at a mounted installer volume.", path, "observed"))
    if "/.Trash/" in path or classification == GenerationClassification.TRASH:
        items.append(_item(registration, "trash_path", True, "snapshot", 0.95, "Observed evidence: registration path points inside Finder Trash.", path, "observed"))
    if "Updater" in path or "Updater" in (registration.bundle_id or ""):
        items.append(_item(registration, "updater_path", True, "snapshot", 0.9, "Observed evidence: registration path or bundle identifier belongs to an updater helper.", {"path": path, "bundle_id": registration.bundle_id}, "observed"))
    if classification == GenerationClassification.ACTIVE and path.startswith("/Applications/"):
        items.append(_item(registration, "active_application_bundle_path", True, "snapshot", 0.96, "Observed evidence: active application bundle path exists under /Applications.", path, "observed"))
    return items


def _trace_evidence(registration: GenerationRegistration, trace_analysis: dict[str, Any] | None) -> list[LaunchServicesProducerEvidenceItem]:
    if trace_analysis is None:
        return [
            _item(registration, "security_privacy_trace_reads_csstore", False, "trace unavailable", 0.0, "Unknown: no trace was provided, so SecurityPrivacyExtension .csstore reads were not observed.", None, "unknown"),
            _item(registration, "system_settings_trace_observed", False, "trace unavailable", 0.0, "Unknown: no trace was provided, so System Settings Privacy UI activity was not observed.", None, "unknown"),
            _item(registration, "runningboard_trace_observed", False, "trace unavailable", 0.0, "Unknown: no trace was provided, so RunningBoard activity was not observed.", None, "unknown"),
        ]
    signal_counts = trace_analysis.get("signal_counts", {}) if isinstance(trace_analysis, dict) else {}
    blob = str(trace_analysis).lower()
    consumer_observed = _securityprivacy_csstore_consumer_observed(trace_analysis)
    return [
        _trace_item(
            registration,
            trace_analysis,
            "security_privacy_trace_reads_csstore",
            consumer_observed,
            "SecurityPrivacyExtension and .csstore access were observed in the same trace window/process context; this is consumer evidence.",
            observed_category="observed_consumer",
        ),
        _trace_item(registration, trace_analysis, "system_settings_trace_observed", "system settings" in blob or "privacy" in blob, "System Settings / Privacy UI activity was observed in trace artifacts."),
        _trace_item(registration, trace_analysis, "runningboard_trace_observed", _signal_count(signal_counts, "runningboard", blob) > 0, "RunningBoard process/app lifecycle activity was observed in trace artifacts."),
    ]


def _trace_item(
    registration: GenerationRegistration,
    trace_analysis: dict[str, Any],
    evidence_type: str,
    observed: bool,
    observed_reason: str,
    *,
    observed_category: str = "observed",
) -> LaunchServicesProducerEvidenceItem:
    if observed:
        return _item(registration, evidence_type, True, "trace", 0.86, f"Observed evidence: {observed_reason}", _raw_trace_reference(trace_analysis, evidence_type), observed_category)
    return _item(registration, evidence_type, False, "trace", 0.2, "Unknown: trace was provided, but this signal was not observed.", _raw_trace_reference(trace_analysis, evidence_type), "unknown")


def _inferred_evidence(registration: GenerationRegistration) -> list[LaunchServicesProducerEvidenceItem]:
    items: list[LaunchServicesProducerEvidenceItem] = []
    path = registration.path or ""
    if "/Applications/" in path:
        items.append(_item(registration, "finder_visible_path", False, "inferred", 0.58, "Inferred evidence: paths under /Applications are normally visible to Finder, but Finder visibility was not directly observed.", path, "inferred"))
        items.append(_item(registration, "spotlight_metadata_present", False, "inferred", 0.52, "Inferred evidence: application bundles may be indexed by Spotlight, but Spotlight metadata was not directly collected.", path, "inferred"))
    return items


def _item(registration: GenerationRegistration, evidence_type: str, observed: bool, source: str, confidence: float, reasoning: str, raw_reference: Any, category: str) -> LaunchServicesProducerEvidenceItem:
    registration_id = _registration_id(registration)
    basis = "|".join([registration_id, evidence_type, source, str(raw_reference)])
    return LaunchServicesProducerEvidenceItem(
        evidence_id=f"ls-prod-{hashlib.sha256(basis.encode()).hexdigest()[:12]}",
        target_registration_id=registration_id,
        generation_id=registration.generation_id,
        path=registration.path,
        evidence_type=evidence_type,
        observed=observed,
        source=source,
        confidence=confidence,
        reasoning=reasoning,
        raw_reference=raw_reference,
        category=category,
    )


def _registration_id(registration: GenerationRegistration) -> str:
    basis = "|".join([registration.generation_id, registration.path or "", registration.bundle_id or "", registration.role])
    return f"ls-reg-{hashlib.sha256(basis.encode()).hexdigest()[:12]}"


def _signal_count(signal_counts: Any, key: str, blob: str) -> int:
    if isinstance(signal_counts, dict):
        value = signal_counts.get(key, 0)
        if isinstance(value, int):
            return value
    return 1 if key.lower() in blob else 0


def _securityprivacy_csstore_consumer_observed(trace_analysis: dict[str, Any]) -> bool:
    events = trace_analysis.get("timeline_events", [])
    if not isinstance(events, list):
        return False
    security_processes = {
        str(event.get("process", "")).lower()
        for event in events
        if isinstance(event, dict)
        and str(event.get("signal", "")).lower() == "securityprivacyextension"
        and "securityprivacyextension" in str(event.get("process", "")).lower()
    }
    if not security_processes:
        return False
    for event in events:
        if not isinstance(event, dict):
            continue
        process = str(event.get("process", "")).lower()
        signal = str(event.get("signal", "")).lower()
        line = str(event.get("line", "")).lower()
        paths_value = event.get("paths", [])
        paths = " ".join(str(path).lower() for path in paths_value if isinstance(path, str)) if isinstance(paths_value, list) else ""
        if process in security_processes and (signal == "launchservices_csstore" or ".csstore" in line or ".csstore" in paths):
            return True
    return False


def _raw_trace_reference(trace_analysis: dict[str, Any], evidence_type: str) -> dict[str, Any]:
    wanted = {
        "security_privacy_trace_reads_csstore": {"securityprivacyextension", "launchservices_csstore"},
        "system_settings_trace_observed": {"securityprivacyextension", "tcc_localnetwork"},
        "runningboard_trace_observed": {"runningboard"},
    }.get(evidence_type, set())
    events = []
    for event in trace_analysis.get("timeline_events", []):
        if isinstance(event, dict) and str(event.get("signal")) in wanted:
            events.append({key: event.get(key) for key in ["timestamp", "source_file", "signal", "process", "line"]})
    return {"signals": sorted(wanted), "events": events[:5]}


def _trace_observed_labels(items: Sequence[LaunchServicesProducerEvidenceItem]) -> list[str]:
    labels = {
        "security_privacy_trace_reads_csstore": "SecurityPrivacyExtension observed",
        "system_settings_trace_observed": "System Settings Privacy UI observed",
        "runningboard_trace_observed": "RunningBoard observed",
    }
    result = {labels[item.evidence_type] for item in items if item.observed and item.evidence_type in labels}
    if any(item.observed and item.evidence_type == "security_privacy_trace_reads_csstore" for item in items):
        result.add(".csstore reads observed")
    ordered = ["RunningBoard observed", "SecurityPrivacyExtension observed", "System Settings Privacy UI observed", ".csstore reads observed"]
    return [label for label in ordered if label in result]


def _observed_summary_lines(items: Sequence[LaunchServicesProducerEvidenceItem]) -> list[str]:
    paths = [item.path or "" for item in items]
    lines: set[str] = set()
    if any(item.evidence_type == "lsregister_dump_contains_path" and item.observed and "Helper" in (item.path or "") for item in items):
        lines.add("lsregister dump contains Chrome helper paths")
    if any(item.evidence_type == "registration_path_exists" and item.observed and (item.path or "").startswith("/Applications/") for item in items):
        lines.add("registration paths exist under /Applications")
    if any(item.evidence_type == "trash_path" and item.observed for item in items):
        lines.add("Trash Chrome path is still registered")
    if any(item.evidence_type == "mounted_volume_path" and item.observed for item in items):
        lines.add("/Volumes Google Chrome path is registered")
    if any(item.evidence_type == "updater_path" and item.observed for item in items):
        lines.add("updater path is registered")
    if any("Chrome" in path for path in paths) and not lines:
        lines.add("LaunchServices snapshot contains Chrome registrations")
    return sorted(lines)


def _inferred_summary_lines(items: Sequence[LaunchServicesProducerEvidenceItem]) -> list[str]:
    lines = set()
    if any(item.evidence_type in {"csstore_candidate_contains_path", "registration_path_missing"} and item.observed for item in items):
        lines.add("persistence likely derived from LaunchServices cache")
    if any(item.category == "inferred" for item in items):
        lines.add("Finder/Spotlight consumer evidence is modeled unless directly observed")
    return sorted(lines)


def _consumer_evidence_summary_lines(items: Sequence[LaunchServicesProducerEvidenceItem]) -> list[str]:
    lines = set()
    if any(item.evidence_type == "security_privacy_trace_reads_csstore" and item.observed and item.category == "observed_consumer" for item in items):
        lines.add("SecurityPrivacyExtension .csstore consumer evidence observed")
    if any(item.evidence_type == "system_settings_trace_observed" and item.observed for item in items):
        lines.add("System Settings Privacy UI consumer context observed")
    if any(item.evidence_type == "runningboard_trace_observed" and item.observed for item in items):
        lines.add("RunningBoard process context observed")
    return sorted(lines)


def _unknown_summary_lines(items: Sequence[LaunchServicesProducerEvidenceItem]) -> list[str]:
    if any(item.category == "unknown" and item.source == "trace unavailable" for item in items):
        return ["trace-backed consumer evidence not observed because no trace was provided"]
    if any(item.category == "unknown" for item in items):
        return ["some trace-backed consumer evidence was not observed"]
    return []
