from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticEvidence
from macos_state_explorer.launchservices.models import LaunchServicesStatus


@dataclass(frozen=True)
class LocalNetworkHistoricalEvidence:
    launchservices_stale_count: int
    tcc_missing_localnetwork_rows: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "launchservices_stale_count": self.launchservices_stale_count,
            "tcc_missing_localnetwork_rows": self.tcc_missing_localnetwork_rows,
        }


@dataclass(frozen=True)
class LocalNetworkFunctionalState:
    status: str
    local_network_ui: str
    chrome_entry_count: int | None
    permission_enabled: bool | None
    communication: str
    networkextension: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "local_network_ui": self.local_network_ui,
            "chrome_entry_count": self.chrome_entry_count,
            "permission_enabled": self.permission_enabled,
            "communication": self.communication,
            "networkextension": self.networkextension,
        }


@dataclass(frozen=True)
class LocalNetworkConfidenceScores:
    historical_confidence: float
    failure_confidence: float

    def to_json_dict(self) -> dict[str, float]:
        return {
            "historical_confidence": self.historical_confidence,
            "failure_confidence": self.failure_confidence,
        }


@dataclass(frozen=True)
class LocalNetworkReasoning:
    historical_evidence: LocalNetworkHistoricalEvidence
    current_functional_state: LocalNetworkFunctionalState
    current_risk: str
    diagnosis_state: str
    confidence_scores: LocalNetworkConfidenceScores
    conclusion: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "historical_evidence": self.historical_evidence.to_json_dict(),
            "current_functional_state": self.current_functional_state.to_json_dict(),
            "current_risk": self.current_risk,
            "diagnosis_state": self.diagnosis_state,
            "confidence_scores": self.confidence_scores.to_json_dict(),
        }


def build_local_network_reasoning(
    snapshot: Snapshot,
    trace_analysis: dict[str, Any] | None = None,
) -> LocalNetworkReasoning:
    payloads = {observation.collector: observation.payload for observation in snapshot.observations}
    launchservices = payloads.get("launchservices", {})
    tcc = payloads.get("tcc", {})
    functional_payload = _functional_payload(payloads, trace_analysis)
    historical = LocalNetworkHistoricalEvidence(
        launchservices_stale_count=_launchservices_stale_count(launchservices if isinstance(launchservices, dict) else {}),
        tcc_missing_localnetwork_rows=not _has_localnetwork_rows(tcc if isinstance(tcc, dict) else {}),
    )
    functional = _functional_state(functional_payload, tcc if isinstance(tcc, dict) else {})
    return _reasoning_from_layers(historical, functional)


def build_local_network_reasoning_from_evidence(
    evidence: Sequence[DiagnosticEvidence],
    trace_analysis: dict[str, Any] | None = None,
) -> LocalNetworkReasoning:
    evidence_by_id = {item.id: item for item in evidence}
    stale_count = _stale_count_from_evidence(evidence)
    historical = LocalNetworkHistoricalEvidence(
        launchservices_stale_count=stale_count,
        tcc_missing_localnetwork_rows=bool(evidence_by_id.get("LN-E001") and evidence_by_id["LN-E001"].present),
    )
    functional = _functional_state(_functional_payload({}, trace_analysis), {})
    return _reasoning_from_layers(historical, functional)


def render_reasoning_summary(summary: dict[str, Any]) -> str:
    historical = summary.get("historical_evidence") if isinstance(summary.get("historical_evidence"), dict) else {}
    functional = summary.get("current_functional_state") if isinstance(summary.get("current_functional_state"), dict) else {}
    scores = summary.get("confidence_scores") if isinstance(summary.get("confidence_scores"), dict) else {}
    return "\n".join(
        [
            "Historical observations",
            f"- LaunchServices stale/orphaned registrations: {historical.get('launchservices_stale_count', 0)}",
            f"- Missing TCC Local Network rows observed historically: {historical.get('tcc_missing_localnetwork_rows', False)}",
            "",
            "Current functional state",
            f"- Status: {functional.get('status', 'UNKNOWN')}",
            f"- Local Network UI: {functional.get('local_network_ui', 'unknown')}",
            f"- Chrome entries: {functional.get('chrome_entry_count', 'unknown')}",
            f"- Permission enabled: {functional.get('permission_enabled', 'unknown')}",
            f"- Communication: {functional.get('communication', 'unknown')}",
            "",
            f"Risk: {summary.get('current_risk', 'UNKNOWN')}",
            f"Diagnosis state: {summary.get('diagnosis_state', 'UNKNOWN')}",
            (
                "Confidence: "
                f"historical {float(scores.get('historical_confidence', 0.0)):.0%}, "
                f"failure {float(scores.get('failure_confidence', 0.0)):.0%}"
            ),
        ]
    )


def _reasoning_from_layers(
    historical: LocalNetworkHistoricalEvidence,
    functional: LocalNetworkFunctionalState,
) -> LocalNetworkReasoning:
    historical_confidence = 0.9 if historical.launchservices_stale_count else 0.1
    if historical.tcc_missing_localnetwork_rows:
        historical_confidence = max(historical_confidence, 0.75)

    if functional.status == "BROKEN":
        risk = "HIGH"
        state = "BROKEN"
        failure_confidence = 0.92
        conclusion = "NetworkExtension or Local Network functional state is broken."
    elif functional.status == "DEGRADED":
        risk = "MEDIUM"
        state = "DEGRADED_WITH_HISTORICAL_EVIDENCE" if historical.launchservices_stale_count else "DEGRADED"
        failure_confidence = 0.7
        conclusion = "Local Network communication is currently failing; historical evidence may be relevant but is not sufficient alone."
    elif functional.status == "HEALTHY" and historical.launchservices_stale_count:
        risk = "LOW"
        state = "HEALTHY_WITH_HISTORICAL_EVIDENCE"
        failure_confidence = 0.2
        conclusion = "Historical LaunchServices orphaned registrations remain present but are not currently affecting Local Network functionality."
    elif functional.status == "HEALTHY":
        risk = "LOW"
        state = "HEALTHY"
        failure_confidence = 0.1
        conclusion = "Local Network permissions are healthy and current communication evidence is working."
    elif historical.launchservices_stale_count:
        risk = "UNKNOWN"
        state = "HISTORICAL_EVIDENCE_FUNCTIONAL_STATE_UNKNOWN"
        failure_confidence = 0.45
        conclusion = "Historical LaunchServices evidence remains present, but current Local Network functionality is not established by this snapshot."
    elif historical.tcc_missing_localnetwork_rows:
        risk = "MEDIUM"
        state = "MISSING_CURRENT_PERMISSION_EVIDENCE"
        failure_confidence = 0.65
        conclusion = "Current TCC evidence does not show Local Network permission rows."
    else:
        risk = "UNKNOWN"
        state = "UNKNOWN"
        failure_confidence = 0.35
        conclusion = "The current read-only snapshot does not establish a specific Local Network failure."

    return LocalNetworkReasoning(
        historical_evidence=historical,
        current_functional_state=functional,
        current_risk=risk,
        diagnosis_state=state,
        confidence_scores=LocalNetworkConfidenceScores(
            historical_confidence=round(historical_confidence, 2),
            failure_confidence=round(failure_confidence, 2),
        ),
        conclusion=conclusion,
    )


def _functional_payload(
    payloads: dict[str, Any],
    trace_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(trace_analysis, dict) and isinstance(trace_analysis.get("functional_state"), dict):
        return trace_analysis["functional_state"]
    value = payloads.get("local_network_functional_state")
    return value if isinstance(value, dict) else {}


def _functional_state(payload: dict[str, Any], tcc_payload: dict[str, Any]) -> LocalNetworkFunctionalState:
    local_network_ui = str(payload.get("local_network_ui", "unknown")).lower()
    communication = str(payload.get("communication", "unknown")).lower()
    networkextension = str(payload.get("networkextension", "unknown")).lower()
    chrome_entry_count = _optional_int(payload.get("chrome_entry_count"))
    permission_enabled = _optional_bool(payload.get("permission_enabled"))
    if permission_enabled is None and _has_localnetwork_rows(tcc_payload):
        permission_enabled = True
    if chrome_entry_count is None:
        chrome_entry_count = _chrome_localnetwork_entry_count(tcc_payload)

    if networkextension == "broken" or local_network_ui == "broken" or permission_enabled is False:
        status = "BROKEN"
    elif communication == "failed":
        status = "DEGRADED"
    elif local_network_ui == "healthy" and chrome_entry_count == 1 and permission_enabled is True and communication == "successful":
        status = "HEALTHY"
    elif permission_enabled is True and chrome_entry_count == 1 and communication == "successful":
        status = "HEALTHY"
    else:
        status = "UNKNOWN"

    return LocalNetworkFunctionalState(
        status=status,
        local_network_ui=local_network_ui,
        chrome_entry_count=chrome_entry_count,
        permission_enabled=permission_enabled,
        communication=communication,
        networkextension=networkextension,
    )


def _launchservices_stale_count(payload: dict[str, Any]) -> int:
    stale_entries = payload.get("stale_entries")
    if isinstance(stale_entries, list):
        return len(stale_entries)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return 0
    stale_statuses = {
        LaunchServicesStatus.ORPHANED.value,
        LaunchServicesStatus.MISSING_VOLUME.value,
        LaunchServicesStatus.STALE.value,
    }
    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        classification = entry.get("classification")
        if classification in stale_statuses or entry.get("path_exists") is False or entry.get("node_not_found") is True:
            count += 1
    return count


def _stale_count_from_evidence(evidence: Sequence[DiagnosticEvidence]) -> int:
    count = 0
    for item in evidence:
        if not item.present or "launchservices" not in item.source.lower():
            continue
        found = re.search(r"(\d+)", item.detail)
        if found:
            count = max(count, int(found.group(1)))
        else:
            count = max(count, 1)
    return count


def _has_localnetwork_rows(payload: dict[str, Any]) -> bool:
    direct = payload.get("direct_localnetwork_query", {})
    stdout = str(direct.get("stdout", "")) if isinstance(direct, dict) else ""
    if stdout.strip():
        return True
    for key in ("user_tcc", "system_tcc", "regdb"):
        section = payload.get(key, {})
        if isinstance(section, dict) and _contains_localnetwork(section.get("hits", [])):
            return True
    return False


def _chrome_localnetwork_entry_count(payload: dict[str, Any]) -> int | None:
    direct = payload.get("direct_localnetwork_query", {})
    stdout = str(direct.get("stdout", "")) if isinstance(direct, dict) else ""
    if not stdout.strip():
        return None
    count = stdout.lower().count("com.google.chrome")
    return count or None


def _contains_localnetwork(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_localnetwork(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_localnetwork(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "ktccservicelocalnetwork" in lowered or "localnetwork" in lowered
    return False


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "yes", "1", "enabled", "allowed"}:
            return True
        if lowered in {"false", "no", "0", "disabled", "denied"}:
            return False
    return None
