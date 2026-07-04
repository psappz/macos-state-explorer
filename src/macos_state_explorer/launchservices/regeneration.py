from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from typing import Any

from macos_state_explorer.launchservices.generations import Generation, GenerationAnalysis
from macos_state_explorer.launchservices.outcome import ExecutePlanAuditHistory
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance

EVIDENCE_CATEGORIES = ("Observed", "Correlated", "Inferred", "Unknown")


@dataclass(frozen=True)
class RegenerationEvidence:
    category: str
    label: str
    source: str
    confidence: float
    detail: str
    raw_reference: Any

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": self.label,
            "source": self.source,
            "confidence": round(self.confidence, 4),
            "detail": self.detail,
            "raw_reference": self.raw_reference,
        }


@dataclass(frozen=True)
class GenerationRegeneration:
    generation_id: str
    product_family: str
    version: str | None
    classification: str
    registration_count: int
    producer: str
    regenerator: str
    confidence: float
    observed_evidence: list[RegenerationEvidence]
    correlated_evidence: list[RegenerationEvidence]
    inferred_evidence: list[RegenerationEvidence]
    unknown_evidence: list[RegenerationEvidence]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "product_family": self.product_family,
            "version": self.version,
            "classification": self.classification,
            "registration_count": self.registration_count,
            "producer": self.producer,
            "regenerator": self.regenerator,
            "confidence": round(self.confidence, 4),
            "evidence_categories": [category for category, items in self._category_items() if items],
            "observed_evidence": [item.to_json_dict() for item in self.observed_evidence],
            "correlated_evidence": [item.to_json_dict() for item in self.correlated_evidence],
            "inferred_evidence": [item.to_json_dict() for item in self.inferred_evidence],
            "unknown_evidence": [item.to_json_dict() for item in self.unknown_evidence],
        }

    def _category_items(self) -> list[tuple[str, list[RegenerationEvidence]]]:
        return [
            ("Observed", self.observed_evidence),
            ("Correlated", self.correlated_evidence),
            ("Inferred", self.inferred_evidence),
            ("Unknown", self.unknown_evidence),
        ]


@dataclass(frozen=True)
class LaunchServicesRegeneration:
    regeneration_id: str
    timestamp: str
    generations: list[GenerationRegeneration]
    trace_context: dict[str, Any]
    audit_context: dict[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "launchservices regeneration",
            "regeneration_id": self.regeneration_id,
            "timestamp": self.timestamp,
            "generation_count": len(self.generations),
            "summary": regeneration_summary(self),
            "generations": [generation.to_json_dict() for generation in self.generations],
            "trace_context": dict(self.trace_context),
            "audit_context": dict(self.audit_context),
        }


def build_launchservices_regeneration(
    analysis: GenerationAnalysis,
    *,
    trace_analysis: dict[str, Any] | None = None,
    audit_history: ExecutePlanAuditHistory | None = None,
) -> LaunchServicesRegeneration:
    provenance = build_launchservices_provenance(analysis)
    producer_by_generation = _producer_by_generation(provenance.to_json_dict())
    generations = [
        _generation_regeneration(
            generation,
            producer_by_generation.get(generation.generation_id, "Unknown"),
            trace_analysis,
            audit_history,
        )
        for generation in analysis.generations
    ]
    generations.sort(key=lambda item: (item.product_family, item.generation_id))
    digest_basis = "|".join(f"{item.generation_id}:{item.regenerator}:{item.confidence}" for item in generations)
    regeneration_id = f"ls-regeneration-{hashlib.sha256(digest_basis.encode()).hexdigest()[:12]}"
    return LaunchServicesRegeneration(
        regeneration_id=regeneration_id,
        timestamp="1970-01-01T00:00:00Z",
        generations=generations,
        trace_context={"available": trace_analysis is not None},
        audit_context=_audit_context(audit_history),
    )


def regeneration_summary(regeneration: LaunchServicesRegeneration) -> dict[str, Any]:
    regenerators = Counter(generation.regenerator for generation in regeneration.generations)
    high_confidence = [generation for generation in regeneration.generations if generation.confidence >= 0.8]
    unknown = [generation for generation in regeneration.generations if generation.regenerator == "Unknown"]
    top_regenerator = "Unknown"
    if regenerators:
        top_regenerator = sorted(regenerators.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "regeneration_id": regeneration.regeneration_id,
        "generation_count": len(regeneration.generations),
        "top_regenerator": top_regenerator,
        "high_confidence_generation_count": len(high_confidence),
        "unknown_generation_count": len(unknown),
        "regenerators": dict(sorted(regenerators.items())),
        "trace_available": bool(regeneration.trace_context.get("available")),
        "audit_informed": bool(regeneration.audit_context.get("source_count")),
    }


def local_network_regeneration_summary(regeneration: LaunchServicesRegeneration) -> dict[str, Any]:
    summary = regeneration_summary(regeneration)
    return {
        "top_regenerator": summary["top_regenerator"],
        "high_confidence_generation_count": summary["high_confidence_generation_count"],
        "unknown_generation_count": summary["unknown_generation_count"],
        "trace_available": summary["trace_available"],
        "audit_informed": summary["audit_informed"],
    }


def render_regeneration_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "LaunchServices regeneration",
            f"- Top regenerator: {summary.get('top_regenerator', 'Unknown')}",
            f"- High confidence generations: {summary.get('high_confidence_generation_count', 0)}",
            f"- Unknown generations: {summary.get('unknown_generation_count', 0)}",
        ]
    )


def render_launchservices_regeneration(regeneration: LaunchServicesRegeneration) -> str:
    lines = ["LaunchServices regeneration analysis", ""]
    for generation in regeneration.generations:
        lines.append("Generation")
        lines.append(generation.generation_id)
        lines.append(f"Producer: {generation.producer}")
        lines.append(f"Regenerator: {generation.regenerator}")
        lines.append(f"Confidence: {generation.confidence:.0%}")
        for title, items in [
            ("Observed", generation.observed_evidence),
            ("Correlated", generation.correlated_evidence),
            ("Inferred", generation.inferred_evidence),
            ("Unknown", generation.unknown_evidence),
        ]:
            lines.append(title)
            for item in items or [_empty_evidence(title)]:
                lines.append(f"- {item.label}: {item.detail}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _generation_regeneration(
    generation: Generation,
    producer: str,
    trace_analysis: dict[str, Any] | None,
    audit_history: ExecutePlanAuditHistory | None,
) -> GenerationRegeneration:
    observed: list[RegenerationEvidence] = []
    correlated: list[RegenerationEvidence] = []
    inferred: list[RegenerationEvidence] = []
    unknown: list[RegenerationEvidence] = []

    history_state = _history_state(generation.generation_id, audit_history)
    if history_state in {"attempted_no_persistent_change", "attempted_unknown", "attempted_but_present_again"}:
        observed.append(
            RegenerationEvidence(
                "Observed",
                "execute-plan audit",
                "audit",
                0.92 if history_state == "attempted_no_persistent_change" else 0.65,
                f"Confirmed execute-plan history recorded {history_state} for this generation.",
                {"generation_id": generation.generation_id, "history_state": history_state},
            )
        )

    events = _trace_events(trace_analysis)
    google_updater_events = [event for event in events if _mentions(event, "googleupdater")]
    launchagent_events = [event for event in events if _mentions(event, "launchagent") or _mentions(event, "launchctl")]
    cache_rebuild_events = [event for event in events if _mentions(event, "launchservices") and (_mentions(event, "rebuild") or _mentions(event, "csstore"))]
    security_privacy_events = [event for event in events if _mentions(event, "securityprivacyextension")]

    for event in google_updater_events[:3]:
        observed.append(_event_evidence("Observed", "GoogleUpdater.app", event, "GoogleUpdater activity was observed in trace artifacts."))
    for event in launchagent_events[:3]:
        observed.append(_event_evidence("Observed", "launchctl", event, "LaunchAgent or launchctl activity was observed in trace artifacts."))
    for event in cache_rebuild_events[:3]:
        correlated.append(_event_evidence("Correlated", "LaunchServices cache rebuild", event, "LaunchServices cache rebuild/cache access was temporally available as correlated evidence."))
    for event in security_privacy_events[:3]:
        unknown.append(_event_evidence("Unknown", "SecurityPrivacyExtension", event, "SecurityPrivacyExtension was observed, but this engine does not classify it as the regenerator without direct correlated producer evidence."))

    if generation.product_family in {"GoogleUpdater", "EdgeUpdater"}:
        inferred.append(
            RegenerationEvidence(
                "Inferred",
                f"{generation.product_family} registration",
                "generation model",
                0.55,
                "Updater generation identity is inferred from LaunchServices registration paths and bundle identifiers.",
                generation.generation_id,
            )
        )

    if not observed and not correlated and not inferred:
        unknown.append(
            RegenerationEvidence(
                "Unknown",
                "regenerator unavailable",
                "analysis",
                0.0,
                "No trace or audit evidence identifies a regeneration source for this generation.",
                generation.generation_id,
            )
        )

    regenerator, confidence = _regenerator_and_confidence(generation, history_state, observed, correlated, inferred)
    return GenerationRegeneration(
        generation_id=generation.generation_id,
        product_family=generation.product_family,
        version=generation.version,
        classification=generation.classification.value,
        registration_count=len(generation.registrations),
        producer=producer,
        regenerator=regenerator,
        confidence=confidence,
        observed_evidence=_dedupe(observed),
        correlated_evidence=_dedupe(correlated),
        inferred_evidence=_dedupe(inferred),
        unknown_evidence=_dedupe(unknown),
    )


def _regenerator_and_confidence(generation: Generation, history_state: str | None, observed: list[RegenerationEvidence], correlated: list[RegenerationEvidence], inferred: list[RegenerationEvidence]) -> tuple[str, float]:
    labels = {item.label for item in observed}
    if "GoogleUpdater.app" in labels and "launchctl" in labels and correlated:
        confidence = 0.98 if history_state in {"attempted_no_persistent_change", "attempted_unknown", "attempted_but_present_again"} else 0.91
        return "GoogleUpdater LaunchAgent", confidence
    if generation.product_family == "GoogleUpdater" and observed:
        return "GoogleUpdater", 0.86
    if generation.product_family == "EdgeUpdater" and observed:
        return "EdgeUpdater", 0.86
    if observed and correlated:
        best = sorted(observed, key=lambda item: (-item.confidence, item.label))[0]
        return best.label, min(0.79, best.confidence)
    if inferred:
        return inferred[0].label, min(0.55, inferred[0].confidence)
    return "Unknown", 0.25


def _producer_by_generation(provenance_payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in provenance_payload.get("registrations", []):
        if isinstance(item, dict) and isinstance(item.get("generation_id"), str):
            result.setdefault(item["generation_id"], str(item.get("producer") or "Unknown"))
    return result


def _trace_events(trace_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(trace_analysis, dict):
        return []
    events = trace_analysis.get("normalized_events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _history_state(generation_id: str, audit_history: ExecutePlanAuditHistory | None) -> str | None:
    if audit_history is None:
        return None
    return audit_history.by_generation.get(generation_id)


def _audit_context(audit_history: ExecutePlanAuditHistory | None) -> dict[str, Any]:
    if audit_history is None:
        return {"source_count": 0, "sources": [], "generation_count": 0}
    raw_sources = getattr(audit_history, "sources", None)
    sources = list(raw_sources or ([audit_history.source] if audit_history.source else []))
    return {"source_count": len(sources), "sources": sources, "generation_count": len(audit_history.by_generation)}


def _mentions(event: dict[str, Any], needle: str) -> bool:
    blob = " ".join(str(event.get(key, "")) for key in ["process", "operation", "path", "file_path", "source", "source_file", "signal", "raw_reference"]).lower()
    return needle.lower() in blob


def _event_evidence(category: str, label: str, event: dict[str, Any], detail: str) -> RegenerationEvidence:
    return RegenerationEvidence(
        category=category,
        label=label,
        source=str(event.get("source") or event.get("source_file") or "trace"),
        confidence=float(event.get("confidence") or (0.85 if category in {"Observed", "Correlated"} else 0.25)),
        detail=detail,
        raw_reference=event.get("raw_reference") or event,
    )


def _empty_evidence(category: str) -> RegenerationEvidence:
    return RegenerationEvidence(category, "none", "analysis", 0.0, "none", None)


def _dedupe(items: list[RegenerationEvidence]) -> list[RegenerationEvidence]:
    seen: set[tuple[str, str, str]] = set()
    result: list[RegenerationEvidence] = []
    for item in sorted(items, key=lambda value: (value.category, value.label, value.source, value.detail)):
        key = (item.category, item.label, item.detail)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
