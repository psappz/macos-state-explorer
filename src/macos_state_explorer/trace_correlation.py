from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Sequence

SIGNAL_LABELS = {
    "securityprivacyextension": "SecurityPrivacyExtension",
    "launchservices_csstore": "LaunchServices .csstore",
    "runningboard": "RunningBoard",
    "system_settings_privacy": "System Settings Privacy UI",
}


@dataclass(frozen=True)
class TraceCorrelationEvidenceItem:
    correlation_id: str
    trace_window: dict[str, str | float | None]
    producer_process: str
    consumer_process: str
    observed_signals: list[str]
    correlation_strength: str
    confidence: float
    reasoning: str
    evidence: list[dict[str, Any]]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "trace_window": self.trace_window,
            "producer_process": self.producer_process,
            "consumer_process": self.consumer_process,
            "observed_signals": list(self.observed_signals),
            "correlation_strength": self.correlation_strength,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class TraceCorrelationEvidence:
    trace_context: dict[str, Any]
    correlations: list[TraceCorrelationEvidenceItem]
    observed_signals: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        summary = trace_correlation_summary(self)
        return {
            "command": "trace correlate",
            "evidence_id": _stable_id("trace-correlation", self.trace_context, [item.to_json_dict() for item in self.correlations]),
            "trace_context": dict(self.trace_context),
            "correlation_count": len([item for item in self.correlations if item.correlation_strength != "none"]),
            "summary": summary,
            "correlations": [item.to_json_dict() for item in self.correlations],
        }


def build_trace_correlation_evidence(trace_analysis: dict[str, Any] | None, *, trace_source: Path | None = None) -> TraceCorrelationEvidence:
    trace_analysis = trace_analysis if isinstance(trace_analysis, dict) else {}
    events = _events(trace_analysis)
    observed = sorted({str(event.get("signal")) for event in events if event.get("signal")})
    items: list[TraceCorrelationEvidenceItem] = []
    items.append(_securityprivacy_csstore_correlation(events))
    items.append(_runningboard_system_settings_securityprivacy_correlation(events))
    items.append(_launchservices_privacy_ui_correlation(events))
    return TraceCorrelationEvidence(
        trace_context={"available": bool(trace_analysis), "source": str(trace_source) if trace_source is not None else None},
        observed_signals=observed,
        correlations=items,
    )


def trace_correlation_summary(evidence: TraceCorrelationEvidence) -> dict[str, Any]:
    correlated = [
        {
            "correlation_id": item.correlation_id,
            "producer_process": item.producer_process,
            "consumer_process": item.consumer_process,
            "observed_signals": item.observed_signals,
            "correlation_strength": item.correlation_strength,
            "confidence": item.confidence,
        }
        for item in evidence.correlations
        if item.correlation_strength != "none"
    ]
    not_correlated = [
        f"{item.producer_process} -> {item.consumer_process}: {item.reasoning}"
        for item in evidence.correlations
        if item.correlation_strength == "none"
    ]
    inferred = []
    if any(item.correlation_strength in {"strong", "medium"} for item in evidence.correlations):
        inferred.append("correlated trace evidence supports a shared LaunchServices/Privacy UI execution context")
    return {
        "observed_signals": list(evidence.observed_signals),
        "observed": [SIGNAL_LABELS.get(signal, signal) for signal in evidence.observed_signals],
        "correlated": correlated,
        "not_correlated": not_correlated,
        "inferred": inferred,
    }


def render_trace_correlation_evidence(evidence: TraceCorrelationEvidence) -> str:
    payload = evidence.to_json_dict()
    summary = payload["summary"]
    lines = ["Trace Correlation Evidence", "", "Observed"]
    for signal in summary.get("observed", []) or ["none"]:
        lines.append(f"- {signal}")
    lines.extend(["", "Correlated"])
    for item in summary.get("correlated", []) or []:
        lines.append(
            f"- {item['producer_process']} -> {item['consumer_process']} "
            f"({item['correlation_strength']}, confidence {item['confidence']:.0%})"
        )
    if not summary.get("correlated"):
        lines.append("- none")
    lines.extend(["", "Not correlated"])
    for item in summary.get("not_correlated", []) or ["none"]:
        lines.append(f"- {item}")
    lines.extend(["", "Inferred"])
    for item in summary.get("inferred", []) or ["none"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def render_trace_correlation_summary(summary: dict[str, Any]) -> str:
    lines = ["Correlation summary", "Observed"]
    for item in summary.get("observed", []) or ["none"]:
        lines.append(f"- {item}")
    lines.append("Correlated")
    for item in summary.get("correlated", []) or []:
        lines.append(
            f"- {item['producer_process']} -> {item['consumer_process']} "
            f"({item['correlation_strength']}, confidence {item['confidence']:.0%})"
        )
    if not summary.get("correlated"):
        lines.append("- none")
    lines.append("Not correlated")
    for item in summary.get("not_correlated", []) or ["none"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _events(trace_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    raw = trace_analysis.get("normalized_events") or trace_analysis.get("timeline_events", [])
    if not isinstance(raw, list):
        return []
    events = [event for event in raw if isinstance(event, dict)]
    return sorted(events, key=lambda event: (_event_sort(event), str(event.get("source_file", "")), str(event.get("signal", ""))))


def _securityprivacy_csstore_correlation(events: Sequence[dict[str, Any]]) -> TraceCorrelationEvidenceItem:
    return _pair_correlation(
        events,
        "securityprivacyextension",
        "launchservices_csstore",
        producer_label="SecurityPrivacyExtension",
        consumer_label="SecurityPrivacyExtension",
        strong_reason="Observed evidence: SecurityPrivacyExtension and LaunchServices .csstore access occurred in the same time window and same process.",
        none_reason="not in same time window/process; two observations are present but not correlated",
    )


def _runningboard_system_settings_securityprivacy_correlation(events: Sequence[dict[str, Any]]) -> TraceCorrelationEvidenceItem:
    runningboard = [event for event in events if event.get("signal") == "runningboard"]
    system = [event for event in events if event.get("signal") == "system_settings_privacy" or "system settings" in str(event.get("line", "")).lower()]
    security = [event for event in events if event.get("signal") == "securityprivacyextension"]
    chain = _best_chain([runningboard, system, security], 10.0)
    if chain is not None:
        return _item(
            "runningboard-systemsettings-securityprivacy",
            chain,
            "RunningBoard",
            "SecurityPrivacyExtension",
            ["runningboard", "system_settings_privacy", "securityprivacyextension"],
            "medium",
            0.74,
            "Observed evidence: RunningBoard, System Settings, and SecurityPrivacyExtension occurred in the same trace window.",
        )
    samples = [*(runningboard[:1]), *(system[:1]), *(security[:1])]
    return _item(
        "runningboard-systemsettings-securityprivacy",
        samples,
        "RunningBoard",
        "SecurityPrivacyExtension",
        ["runningboard", "system_settings_privacy", "securityprivacyextension"],
        "none",
        0.2,
        "not in same time window/process; RunningBoard and SecurityPrivacyExtension observations are not correlated",
    )


def _launchservices_privacy_ui_correlation(events: Sequence[dict[str, Any]]) -> TraceCorrelationEvidenceItem:
    return _pair_correlation(
        events,
        "launchservices_csstore",
        "system_settings_privacy",
        producer_label="LaunchServices",
        consumer_label="Privacy UI",
        strong_reason="Observed evidence: LaunchServices .csstore access and Privacy UI activity occurred in the same trace window.",
        none_reason="not in same time window/process; LaunchServices and Privacy UI observations are not correlated",
        allow_different_process=True,
        confidence=0.68,
        strength="medium",
    )


def _pair_correlation(
    events: Sequence[dict[str, Any]],
    first_signal: str,
    second_signal: str,
    *,
    producer_label: str,
    consumer_label: str,
    strong_reason: str,
    none_reason: str,
    allow_different_process: bool = False,
    confidence: float = 0.91,
    strength: str = "strong",
) -> TraceCorrelationEvidenceItem:
    first = [event for event in events if event.get("signal") == first_signal]
    second = [event for event in events if event.get("signal") == second_signal]
    pair = _best_pair(first, second, 5.0, same_process=not allow_different_process)
    if pair is not None:
        return _item(
            f"{producer_label.lower().replace(' ', '-')}-{consumer_label.lower().replace(' ', '-')}",
            list(pair),
            producer_label,
            consumer_label,
            [first_signal, second_signal],
            strength,
            confidence,
            strong_reason,
        )
    samples = [*(first[:1]), *(second[:1])]
    return _item(
        f"{producer_label.lower().replace(' ', '-')}-{consumer_label.lower().replace(' ', '-')}",
        samples,
        producer_label,
        consumer_label,
        [first_signal, second_signal],
        "none",
        0.2,
        none_reason,
    )


def _item(correlation_id: str, events: Sequence[dict[str, Any]], producer: str, consumer: str, signals: list[str], strength: str, confidence: float, reasoning: str) -> TraceCorrelationEvidenceItem:
    window = _window(events)
    return TraceCorrelationEvidenceItem(
        correlation_id=correlation_id,
        trace_window=window,
        producer_process=producer,
        consumer_process=consumer,
        observed_signals=signals,
        correlation_strength=strength,
        confidence=confidence,
        reasoning=reasoning,
        evidence=[_event_reference(event) for event in events],
    )


def _best_pair(first: Sequence[dict[str, Any]], second: Sequence[dict[str, Any]], seconds: float, *, same_process: bool) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for left in first:
        for right in second:
            delta = _delta_seconds(left, right)
            if delta is None or delta > seconds:
                continue
            if same_process and _process(left) != _process(right):
                continue
            return left, right
    return None


def _best_chain(groups: Sequence[Sequence[dict[str, Any]]], seconds: float) -> list[dict[str, Any]] | None:
    if any(not group for group in groups):
        return None
    for first in groups[0]:
        for second in groups[1]:
            if (_delta_seconds(first, second) or 999999) > seconds:
                continue
            for third in groups[2]:
                if (_delta_seconds(second, third) or 999999) <= seconds:
                    return [first, second, third]
    return None


def _window(events: Sequence[dict[str, Any]]) -> dict[str, str | float | None]:
    if not events:
        return {"start": None, "end": None, "duration_seconds": None}
    ordered = sorted(events, key=_event_sort)
    start = str(ordered[0].get("timestamp", ""))
    end = str(ordered[-1].get("timestamp", ""))
    duration = _delta_seconds(ordered[0], ordered[-1])
    return {"start": start, "end": end, "duration_seconds": duration}


def _event_reference(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": event.get("timestamp", ""),
        "source_file": event.get("source_file", ""),
        "signal": event.get("signal", ""),
        "process": event.get("process", ""),
        "paths": event.get("paths", []),
        "line": event.get("line", ""),
    }


def _process(event: dict[str, Any]) -> str:
    return str(event.get("process", "")).lower()


def _delta_seconds(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    left_dt = _parse_timestamp(str(left.get("timestamp", "")))
    right_dt = _parse_timestamp(str(right.get("timestamp", "")))
    if left_dt is None or right_dt is None:
        return None
    return abs((right_dt - left_dt).total_seconds())


def _event_sort(event: dict[str, Any]) -> str:
    return str(event.get("timestamp", ""))


def _parse_timestamp(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%H:%M:%S.%f", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt.startswith("%H"):
                return parsed.replace(year=2000, month=1, day=1)
            return parsed
        except ValueError:
            continue
    return None


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(repr(parts).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"
