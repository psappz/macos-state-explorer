from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from typing import Any

from macos_state_explorer.launchservices.generations import Generation, GenerationAnalysis, GenerationClassification, GenerationRegistration


@dataclass(frozen=True)
class LaunchServicesRegistrationProvenance:
    registration_id: str
    product_family: str
    generation_id: str
    path: str | None
    producer: str
    producer_confidence: float
    producer_reasoning: str
    persistence_source: str
    regeneration_source: str
    consumer_set: list[str]
    confidence: float
    evidence: list[dict[str, Any]]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "registration_id": self.registration_id,
            "product_family": self.product_family,
            "generation_id": self.generation_id,
            "path": self.path,
            "producer": self.producer,
            "producer_confidence": round(self.producer_confidence, 4),
            "producer_reasoning": self.producer_reasoning,
            "persistence_source": self.persistence_source,
            "regeneration_source": self.regeneration_source,
            "consumer_set": list(self.consumer_set),
            "confidence": round(self.confidence, 4),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class LaunchServicesProvenance:
    provenance_id: str
    timestamp: str
    registrations: list[LaunchServicesRegistrationProvenance]

    def to_json_dict(self) -> dict[str, Any]:
        product_families = sorted({registration.product_family for registration in self.registrations})
        return {
            "command": "launchservices provenance",
            "provenance_id": self.provenance_id,
            "timestamp": self.timestamp,
            "registration_count": len(self.registrations),
            "product_families": product_families,
            "registrations": [registration.to_json_dict() for registration in self.registrations],
            "summary": provenance_summary(self),
        }


def build_launchservices_provenance(analysis: GenerationAnalysis) -> LaunchServicesProvenance:
    registrations: list[LaunchServicesRegistrationProvenance] = []
    for generation in analysis.generations:
        for registration in generation.registrations:
            registrations.append(_registration_provenance(generation, registration))
    registrations.sort(key=lambda item: (item.product_family, item.generation_id, item.path or "", item.registration_id))
    digest_basis = "|".join(f"{item.registration_id}:{item.producer}:{item.persistence_source}" for item in registrations)
    provenance_id = f"ls-provenance-{hashlib.sha256(digest_basis.encode()).hexdigest()[:12]}"
    return LaunchServicesProvenance(provenance_id=provenance_id, timestamp="1970-01-01T00:00:00Z", registrations=registrations)


def provenance_summary(provenance: LaunchServicesProvenance) -> dict[str, Any]:
    producers = Counter(registration.producer for registration in provenance.registrations)
    persistence = Counter(registration.persistence_source for registration in provenance.registrations)
    consumers = sorted({consumer for registration in provenance.registrations for consumer in registration.consumer_set})
    primary = _most_common_label(producers)
    primary_persistence = _most_common_label(persistence)
    product_families = sorted({registration.product_family for registration in provenance.registrations})
    confidence_values = [registration.confidence for registration in provenance.registrations]
    return {
        "registration_count": len(provenance.registrations),
        "product_families": product_families,
        "producers": dict(sorted(producers.items())),
        "primary_producer": primary,
        "persistence_sources": dict(sorted(persistence.items())),
        "persistence_source": primary_persistence,
        "consumers": consumers,
        "confidence": round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else 0.0,
    }


def local_network_provenance_summary(provenance: LaunchServicesProvenance) -> dict[str, Any]:
    summary = provenance_summary(provenance)
    return {
        "primary_producer": summary["primary_producer"],
        "producer_confidence": _confidence_for_label(provenance, "producer", summary["primary_producer"]),
        "producer_reasoning": _reason_for_label(provenance, summary["primary_producer"]),
        "persistence_source": summary["persistence_source"],
        "persistence_confidence": _confidence_for_label(provenance, "persistence_source", summary["persistence_source"]),
        "consumers": summary["consumers"],
        "registration_count": summary["registration_count"],
        "confidence": summary["confidence"],
    }


def render_provenance_summary(summary: dict[str, Any]) -> str:
    lines = ["LaunchServices provenance"]
    lines.append(f"Producer: {summary.get('primary_producer', 'Unknown')}")
    lines.append(f"Confidence: {float(summary.get('producer_confidence', 0.0)):.0%}")
    lines.append(f"Consumers: {', '.join(summary.get('consumers', [])) if summary.get('consumers') else 'none identified'}")
    lines.append(f"Persistence: {summary.get('persistence_source', 'unknown')}")
    lines.append(f"Persistence confidence: {float(summary.get('persistence_confidence', 0.0)):.0%}")
    return "\n".join(lines)


def render_launchservices_provenance(provenance: LaunchServicesProvenance) -> str:
    payload = provenance.to_json_dict()
    lines = ["LaunchServices registration provenance", ""]
    if not provenance.registrations:
        return "\n".join([*lines, "No relevant LaunchServices registrations detected."])
    for product in payload["product_families"]:
        lines.extend([product, "-" * len(product)])
        for registration in [item for item in payload["registrations"] if item["product_family"] == product]:
            lines.append(f"Registration: {registration['registration_id']}")
            lines.append(f"Path: {registration.get('path') or 'unknown'}")
            lines.append(f"Generation: {registration['generation_id']}")
            lines.append(f"Producer: {registration['producer']} ({registration['producer_confidence']:.0%})")
            lines.append(f"Reasoning: {registration['producer_reasoning']}")
            lines.append(f"Consumers: {', '.join(registration['consumer_set'])}")
            lines.append(f"Persistence: {registration['persistence_source']}")
            lines.append(f"Regeneration: {registration['regeneration_source']}")
            lines.append("")
    return "\n".join(lines).rstrip()


def _registration_provenance(generation: Generation, registration: GenerationRegistration) -> LaunchServicesRegistrationProvenance:
    producer, producer_confidence, reasoning = _producer(generation, registration)
    persistence_source, regeneration_source, persistence_confidence = _persistence(generation, registration, producer)
    consumers = _consumers(generation, registration)
    evidence = _evidence(generation, registration, producer, persistence_source)
    confidence = min(producer_confidence, persistence_confidence)
    return LaunchServicesRegistrationProvenance(
        registration_id=_registration_id(registration),
        product_family=generation.product_family,
        generation_id=generation.generation_id,
        path=registration.path,
        producer=producer,
        producer_confidence=producer_confidence,
        producer_reasoning=reasoning,
        persistence_source=persistence_source,
        regeneration_source=regeneration_source,
        consumer_set=consumers,
        confidence=confidence,
        evidence=evidence,
    )


def _producer(generation: Generation, registration: GenerationRegistration) -> tuple[str, float, str]:
    path = registration.path or ""
    bundle_id = registration.bundle_id or ""
    if bundle_id.startswith("com.apple.") or path.startswith("/System/Library/") or path.startswith("/Library/Apple/"):
        return "Apple system registration", 0.95, "Bundle identifier or path identifies an Apple system registration."
    if path.startswith("/Volumes/") or generation.classification == GenerationClassification.MOUNTED_INSTALLER:
        return "Mounted installer", 0.95, "Registration path or generation classification points to a mounted installer volume."
    if "/.Trash/" in path or generation.classification == GenerationClassification.TRASH:
        return "Finder Trash", 0.95, "Registration path or generation classification points to Finder Trash."
    if generation.product_family in {"GoogleUpdater", "EdgeUpdater"} or "Updater" in bundle_id or "Updater" in path:
        return generation.product_family if generation.product_family in {"GoogleUpdater", "EdgeUpdater"} else "GoogleUpdater", 0.9, "Updater bundle identifier or path is present in the LaunchServices registration."
    if path.startswith("/Applications/") or generation.classification in {GenerationClassification.ACTIVE, GenerationClassification.STALE, GenerationClassification.MISSING, GenerationClassification.PARTIAL}:
        return "LaunchServices application enumeration", 0.88, "Registration is grouped as an application generation from LaunchServices records."
    return "Unknown", 0.25, "No producer-specific path, bundle identifier, or generation classification evidence was available."


def _persistence(generation: Generation, registration: GenerationRegistration, producer: str) -> tuple[str, str, float]:
    if producer == "Mounted installer":
        return "mounted volume", "mounted volume enumeration", 0.93
    if producer == "Finder Trash":
        return "trash item", "Finder Trash enumeration", 0.9
    if producer in {"GoogleUpdater", "EdgeUpdater"}:
        return "updater registration", "updater registration", 0.86
    if producer == "Apple system registration":
        return "system registration", "Apple system registration", 0.92
    if producer == "LaunchServices application enumeration":
        if registration.exists_on_disk is False or generation.classification in {GenerationClassification.STALE, GenerationClassification.MISSING, GenerationClassification.PARTIAL}:
            return "derived LaunchServices cache", "rebuilt from application enumeration", 0.86
        return "rebuilt from application enumeration", "application enumeration", 0.88
    return "unknown", "unknown", 0.25


def _consumers(generation: Generation, registration: GenerationRegistration) -> list[str]:
    consumers = {"LaunchServices"}
    path = registration.path or ""
    if generation.product_family in {"Google Chrome", "Microsoft Edge", "GoogleUpdater", "EdgeUpdater"}:
        consumers.update({"SecurityPrivacyExtension", "System Settings Privacy UI", "Finder", "Spotlight"})
    if "/Applications/" in path:
        consumers.add("Finder")
        consumers.add("Spotlight")
    if generation.classification == GenerationClassification.ACTIVE:
        consumers.add("RunningBoard")
    return sorted(consumers)


def _evidence(generation: Generation, registration: GenerationRegistration, producer: str, persistence_source: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {"kind": "generation_id", "value": generation.generation_id},
        {"kind": "classification", "value": generation.classification.value},
        {"kind": "producer", "value": producer},
        {"kind": "persistence_source", "value": persistence_source},
    ]
    if registration.path:
        evidence.append({"kind": "path", "value": registration.path})
    if registration.bundle_id:
        evidence.append({"kind": "bundle_id", "value": registration.bundle_id})
    if registration.exists_on_disk is not None:
        evidence.append({"kind": "exists_on_disk", "value": registration.exists_on_disk})
    return evidence


def _registration_id(registration: GenerationRegistration) -> str:
    basis = "|".join([registration.generation_id, registration.path or "", registration.bundle_id or "", registration.role])
    return f"ls-reg-{hashlib.sha256(basis.encode()).hexdigest()[:12]}"


def _most_common_label(counter: Counter[str]) -> str:
    if not counter:
        return "Unknown"
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _confidence_for_label(provenance: LaunchServicesProvenance, key: str, label: str) -> float:
    if label in {"", "Unknown", "unknown"}:
        return 0.0
    values: list[float] = []
    for registration in provenance.registrations:
        value = getattr(registration, key)
        if value == label:
            values.append(registration.producer_confidence if key == "producer" else registration.confidence)
    return round(sum(values) / len(values), 4) if values else 0.0


def _reason_for_label(provenance: LaunchServicesProvenance, label: str) -> str:
    for registration in provenance.registrations:
        if registration.producer == label:
            return registration.producer_reasoning
    return "No producer-specific evidence was available."
