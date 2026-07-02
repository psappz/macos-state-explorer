from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import plistlib
import re
from pathlib import Path
from typing import Any, Iterable

from macos_state_explorer.launchservices.generations import Generation, GenerationAnalysis
from macos_state_explorer.launchservices.models import LaunchServicesRecord
from macos_state_explorer.networkextension_state import default_networkextension_roots

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
BUNDLE_ID_RE = re.compile(r"\bcom\.[A-Za-z0-9_.-]+\b")
TEAM_ID_RE = re.compile(r"\b[A-Z0-9]{10}\b")


@dataclass(frozen=True)
class IdentityRecord:
    source: str
    source_path: str
    bundle_id: str | None = None
    application_uuid: str | None = None
    team_id: str | None = None
    executable_path: str | None = None
    signing_identity: str | None = None
    runningboard_identity: str | None = None
    security_privacy_extension: bool = False
    raw_reference: str | None = None

    def identity_key(self) -> str:
        return "|".join(
            [
                self.source,
                self.bundle_id or "",
                self.application_uuid or "",
                self.team_id or "",
                self.executable_path or "",
                self.runningboard_identity or "",
                self.source_path,
            ]
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_path": self.source_path,
            "bundle_id": self.bundle_id,
            "application_uuid": self.application_uuid,
            "team_id": self.team_id,
            "executable_path": self.executable_path,
            "signing_identity": self.signing_identity,
            "runningboard_identity": self.runningboard_identity,
            "security_privacy_extension": self.security_privacy_extension,
            "raw_reference": self.raw_reference,
        }


@dataclass(frozen=True)
class IdentityEdge:
    from_node: str
    to_node: str
    relationship: str
    evidence_class: str
    evidence: str

    def to_json_dict(self) -> dict[str, str]:
        return {
            "from": self.from_node,
            "to": self.to_node,
            "relationship": self.relationship,
            "evidence_class": self.evidence_class,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class GenerationIdentityCorrelation:
    generation_id: str
    bundle_identifier: str | None
    relationship: str
    evidence_basis: tuple[str, ...]
    conflicts: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    observed_identity: dict[str, Any] = field(default_factory=dict)
    correlated_identities: tuple[dict[str, Any], ...] = ()
    conclusion_class: str = "Unknown"

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "bundle_identifier": self.bundle_identifier,
            "relationship": self.relationship,
            "conclusion_class": self.conclusion_class,
            "evidence_basis": list(self.evidence_basis),
            "conflicts": list(self.conflicts),
            "missing_evidence": list(self.missing_evidence),
            "observed_identity": self.observed_identity,
            "correlated_identities": list(self.correlated_identities),
        }


@dataclass(frozen=True)
class NetworkExtensionCorrelation:
    correlation_id: str
    generation_correlations: tuple[GenerationIdentityCorrelation, ...]
    identity_records: tuple[IdentityRecord, ...]
    edges: tuple[IdentityEdge, ...]
    roots: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "generation_count": len(self.generation_correlations),
            "confirmed_identical": sum(item.relationship == "confirmed_identical" for item in self.generation_correlations),
            "probable_identical": sum(item.relationship == "probable_identical" for item in self.generation_correlations),
            "conflicting_identity": sum(item.relationship == "conflicting_identity" for item in self.generation_correlations),
            "no_observable_relationship": sum(item.relationship == "no_observable_relationship" for item in self.generation_correlations),
            "unknown": sum(item.relationship == "unknown" for item in self.generation_correlations),
            "read_only": True,
            "mutation_performed": False,
        }

    def summary_for_report(self) -> dict[str, Any]:
        summary = self.summary()
        generation_ids = [item.generation_id for item in self.generation_correlations]
        summary.update(
            {
                "generation_ids": generation_ids,
                "confirmed_generation_ids": [item.generation_id for item in self.generation_correlations if item.relationship == "confirmed_identical"],
                "probable_generation_ids": [item.generation_id for item in self.generation_correlations if item.relationship == "probable_identical"],
                "conflicting_generation_ids": [item.generation_id for item in self.generation_correlations if item.relationship == "conflicting_identity"],
                "unknown_generation_ids": [item.generation_id for item in self.generation_correlations if item.relationship in {"unknown", "no_observable_relationship"}],
            }
        )
        return summary

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension correlate",
            "correlation_id": self.correlation_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "summary": self.summary(),
            "identity_graph": {
                "nodes": [record.to_json_dict() for record in self.identity_records],
                "edges": [edge.to_json_dict() for edge in self.edges],
            },
            "generation_correlations": [item.to_json_dict() for item in self.generation_correlations],
            "roots": list(self.roots),
        }


def build_networkextension_correlation(
    generation_analysis: GenerationAnalysis,
    launchservices_records: Iterable[LaunchServicesRecord | dict[str, Any]],
    *,
    roots: Iterable[Path] | None = None,
    trace_analysis: dict[str, Any] | None = None,
) -> NetworkExtensionCorrelation:
    root_paths = [Path(root).expanduser() for root in (roots if roots is not None else default_networkextension_roots())]
    ls_records = [_record_from_value(record) for record in launchservices_records]
    ne_records = _networkextension_identity_records(root_paths)
    trace_records = _trace_identity_records(trace_analysis)
    identity_records = tuple(sorted([*ne_records, *trace_records], key=lambda item: item.identity_key()))
    ls_by_generation = _launchservices_records_by_generation(generation_analysis, ls_records)
    correlations = tuple(
        _correlate_generation(generation, ls_by_generation.get(generation.generation_id, []), identity_records)
        for generation in generation_analysis.generations
        if generation.product_family in {"Chrome", "Google Chrome"}
    )
    edges = tuple(_build_edges(correlations))
    digest = hashlib.sha256(
        "|".join(
            [item.generation_id + ":" + item.relationship for item in correlations]
            + [edge.from_node + edge.to_node + edge.evidence for edge in edges]
        ).encode()
    ).hexdigest()[:16]
    return NetworkExtensionCorrelation(
        correlation_id=f"networkextension-correlation-{digest}",
        generation_correlations=correlations,
        identity_records=identity_records,
        edges=edges,
        roots=tuple(str(root) for root in root_paths),
    )


def render_networkextension_correlation(correlation: NetworkExtensionCorrelation) -> str:
    summary = correlation.summary()
    lines = [
        "NetworkExtension identity correlation",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Generations: {summary['generation_count']}",
        f"- confirmed_identical: {summary['confirmed_identical']}",
        f"- probable_identical: {summary['probable_identical']}",
        f"- conflicting_identity: {summary['conflicting_identity']}",
        f"- no_observable_relationship: {summary['no_observable_relationship']}",
        "",
        "Generation correlations",
    ]
    if not correlation.generation_correlations:
        lines.append("- none")
    for item in correlation.generation_correlations:
        lines.append(f"- {item.bundle_identifier or item.generation_id} → {item.relationship} ({item.conclusion_class})")
        for evidence in item.evidence_basis:
            lines.append(f"  - {evidence}")
        for conflict in item.conflicts:
            lines.append(f"  - conflict: {conflict}")
        if item.missing_evidence:
            lines.append(f"  - Unknown: {', '.join(item.missing_evidence)}")
    return "\n".join(lines)


def render_networkextension_correlation_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "NetworkExtension identity correlation",
            f"- Confirmed identical: {summary.get('confirmed_identical', 0)}",
            f"- Probable identical: {summary.get('probable_identical', 0)}",
            f"- Conflicting identity: {summary.get('conflicting_identity', 0)}",
            f"- Unknown/no observable relationship: {summary.get('unknown', 0) + summary.get('no_observable_relationship', 0)}",
        ]
    )


def networkextension_correlation_summary(correlation: NetworkExtensionCorrelation) -> dict[str, Any]:
    return correlation.summary_for_report()


def _correlate_generation(generation: Generation, ls_records: list[LaunchServicesRecord], identity_records: tuple[IdentityRecord, ...]) -> GenerationIdentityCorrelation:
    ls_identity = _generation_identity(generation, ls_records)
    candidates = _candidate_records(ls_identity, identity_records)
    evidence: list[str] = []
    conflicts: list[str] = []
    for candidate in candidates:
        _compare_identity(ls_identity, candidate, evidence, conflicts)
    evidence = _ordered_unique(evidence)
    conflicts = _ordered_unique(conflicts)
    if conflicts:
        relationship = "conflicting_identity"
        conclusion_class = "Correlated"
    elif "Observed: shared application UUID" in evidence:
        relationship = "confirmed_identical"
        conclusion_class = "Correlated"
    elif len(evidence) >= 2:
        relationship = "probable_identical"
        conclusion_class = "Correlated"
    elif evidence:
        relationship = "probable_identical"
        conclusion_class = "Correlated"
    else:
        relationship = "no_observable_relationship"
        conclusion_class = "Unknown"
    missing = _missing_evidence(ls_identity, candidates, evidence)
    return GenerationIdentityCorrelation(
        generation_id=generation.generation_id,
        bundle_identifier=generation.bundle_identifier,
        relationship=relationship,
        conclusion_class=conclusion_class,
        evidence_basis=tuple(evidence),
        conflicts=tuple(conflicts),
        missing_evidence=tuple(missing),
        observed_identity=ls_identity,
        correlated_identities=tuple(candidate.to_json_dict() for candidate in candidates),
    )


def _generation_identity(generation: Generation, records: list[LaunchServicesRecord]) -> dict[str, Any]:
    uuids = sorted({str(record.fields.get("application_uuid")) for record in records if record.fields.get("application_uuid")})
    team_ids = sorted({str(record.team_id) for record in records if record.team_id})
    paths = sorted({record.path_clean or record.path for record in records if record.path_clean or record.path})
    executables = sorted({record.executable for record in records if record.executable})
    return {
        "generation_id": generation.generation_id,
        "bundle_id": generation.bundle_identifier,
        "application_uuid": uuids[0] if uuids else None,
        "team_id": team_ids[0] if team_ids else None,
        "executable_path": generation.installation_root or (paths[0] if paths else None),
        "registered_executables": executables,
    }


def _candidate_records(ls_identity: dict[str, Any], records: tuple[IdentityRecord, ...]) -> list[IdentityRecord]:
    result = []
    for record in records:
        if ls_identity.get("application_uuid") and record.application_uuid == ls_identity.get("application_uuid"):
            result.append(record)
        elif ls_identity.get("bundle_id") and record.bundle_id == ls_identity.get("bundle_id"):
            result.append(record)
        elif ls_identity.get("team_id") and record.team_id == ls_identity.get("team_id") and ls_identity.get("executable_path") and record.executable_path == ls_identity.get("executable_path"):
            result.append(record)
    return sorted(result, key=lambda item: item.identity_key())


def _compare_identity(ls_identity: dict[str, Any], candidate: IdentityRecord, evidence: list[str], conflicts: list[str]) -> None:
    _compare_field("application_uuid", "application UUID", ls_identity.get("application_uuid"), candidate.application_uuid, evidence, conflicts)
    _compare_field("bundle_id", "bundle identifier", ls_identity.get("bundle_id"), candidate.bundle_id, evidence, conflicts)
    _compare_field("executable_path", "executable path", ls_identity.get("executable_path"), candidate.executable_path, evidence, conflicts)
    _compare_field("team_id", "Team ID", ls_identity.get("team_id"), candidate.team_id, evidence, conflicts)
    if candidate.source == "trace" or candidate.runningboard_identity:
        evidence.append("Observed: shared trace identity")


def _compare_field(field: str, label: str, left: object, right: object, evidence: list[str], conflicts: list[str]) -> None:
    if left and right and left == right:
        evidence.append(f"Observed: shared {label}")
    elif left and right and left != right:
        conflicts.append(f"{field}: LaunchServices={left} NetworkExtension={right}")


def _missing_evidence(ls_identity: dict[str, Any], candidates: list[IdentityRecord], evidence: list[str]) -> list[str]:
    missing: list[str] = []
    if not candidates:
        missing.append("NetworkExtension preference entry")
    if not ls_identity.get("application_uuid") or not any(candidate.application_uuid for candidate in candidates):
        missing.append("application UUID")
    if not ls_identity.get("team_id") or not any(candidate.team_id for candidate in candidates):
        missing.append("Team ID")
    if "Observed: shared trace identity" not in evidence:
        missing.append("trace identity")
    return missing


def _build_edges(correlations: tuple[GenerationIdentityCorrelation, ...]) -> list[IdentityEdge]:
    edges: list[IdentityEdge] = []
    for item in correlations:
        for identity in item.correlated_identities:
            source = str(identity.get("source", "NetworkExtension"))
            node = identity.get("bundle_id") or identity.get("application_uuid") or identity.get("source_path") or "unknown"
            for evidence in item.evidence_basis:
                edges.append(
                    IdentityEdge(
                        from_node=item.generation_id,
                        to_node=f"{source}:{node}",
                        relationship=item.relationship,
                        evidence_class="Observed" if evidence.startswith("Observed:") else "Correlated",
                        evidence=evidence,
                    )
                )
    return sorted(edges, key=lambda edge: (edge.from_node, edge.to_node, edge.evidence))


def _networkextension_identity_records(roots: list[Path]) -> list[IdentityRecord]:
    records: list[IdentityRecord] = []
    for root in roots:
        for path in _candidate_files(root):
            try:
                text = _decode_file(path)
            except Exception:
                continue
            records.extend(_records_from_text(text, path, root))
    return records


def _candidate_files(root: Path) -> list[Path]:
    root = root.expanduser()
    if root.is_file():
        return [root]
    if root.is_dir():
        return sorted(path for path in root.rglob("*") if path.is_file() and _is_candidate(path))
    return []


def _is_candidate(path: Path) -> bool:
    lower = str(path).lower()
    return any(token in lower for token in ["networkextension", "localnetwork", "local-network", "securityprivacyextension", "systemsettings"])


def _decode_file(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix == ".plist":
        try:
            return json.dumps(plistlib.loads(data), sort_keys=True, default=str)
        except Exception:
            pass
    return data.decode("utf-8", errors="ignore")


def _records_from_text(text: str, path: Path, root: Path) -> list[IdentityRecord]:
    parsed = _parse_json(text)
    objects = _walk_objects(parsed) if parsed is not None else []
    records = [_record_from_mapping(obj, path, root, text) for obj in objects if _looks_identity_mapping(obj)]
    if records:
        return records
    bundle_ids = sorted(set(BUNDLE_ID_RE.findall(text)))
    uuids = sorted(set(UUID_RE.findall(text)))
    team_ids = sorted(set(TEAM_ID_RE.findall(text)))
    result = []
    for bundle_id in bundle_ids:
        result.append(
            IdentityRecord(
                source="NetworkExtension preference",
                source_path=_display_path(path, root),
                bundle_id=bundle_id,
                application_uuid=uuids[0] if uuids else None,
                team_id=team_ids[0] if team_ids else None,
                security_privacy_extension="SecurityPrivacyExtension" in text,
                raw_reference=_short_text(text),
            )
        )
    return result


def _record_from_mapping(obj: dict[str, Any], path: Path, root: Path, text: str) -> IdentityRecord:
    return IdentityRecord(
        source="NetworkExtension preference",
        source_path=_display_path(path, root),
        bundle_id=_first_string(obj, "bundle_id", "bundleIdentifier", "identifier"),
        application_uuid=_first_string(obj, "application_uuid", "applicationUUID", "uuid", "ApplicationUUID"),
        team_id=_first_string(obj, "team_id", "teamID", "TeamID"),
        executable_path=_first_string(obj, "path", "executable_path", "executablePath"),
        signing_identity=_first_string(obj, "signing_identity", "signingIdentity"),
        security_privacy_extension="SecurityPrivacyExtension" in text,
        raw_reference=_short_text(json.dumps(obj, sort_keys=True, default=str)),
    )


def _trace_identity_records(trace_analysis: dict[str, Any] | None) -> list[IdentityRecord]:
    if not isinstance(trace_analysis, dict):
        return []
    objects = _walk_objects(trace_analysis)
    records = []
    for obj in objects:
        if not _looks_identity_mapping(obj):
            continue
        records.append(
            IdentityRecord(
                source="trace",
                source_path="trace_analysis",
                bundle_id=_first_string(obj, "bundle_id", "bundleIdentifier", "identifier"),
                application_uuid=_first_string(obj, "application_uuid", "applicationUUID", "uuid"),
                team_id=_first_string(obj, "team_id", "teamID"),
                executable_path=_first_string(obj, "path", "executable_path", "executablePath"),
                runningboard_identity=_first_string(obj, "runningboard_identity", "runningBoardIdentity", "identity"),
                security_privacy_extension="SecurityPrivacyExtension" in str(obj.get("process", "")),
                raw_reference=_short_text(json.dumps(obj, sort_keys=True, default=str)),
            )
        )
    return records


def _looks_identity_mapping(obj: dict[str, Any]) -> bool:
    return any(_first_string(obj, key) for key in ["bundle_id", "bundleIdentifier", "identifier", "application_uuid", "applicationUUID", "uuid", "team_id", "teamID", "path"])


def _walk_objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        result = [value]
        for child in value.values():
            result.extend(_walk_objects(child))
        return result
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for child in value:
            result.extend(_walk_objects(child))
        return result
    return []


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _first_string(obj: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _short_text(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:240]


def _record_from_value(value: LaunchServicesRecord | dict[str, Any]) -> LaunchServicesRecord:
    if isinstance(value, LaunchServicesRecord):
        return value
    return LaunchServicesRecord(**dict(value))


def _launchservices_records_by_generation(analysis: GenerationAnalysis, records: list[LaunchServicesRecord]) -> dict[str, list[LaunchServicesRecord]]:
    result: dict[str, list[LaunchServicesRecord]] = {generation.generation_id: [] for generation in analysis.generations}
    for generation in analysis.generations:
        paths = {registration.path for registration in generation.registrations if registration.path}
        bundles = {registration.bundle_id for registration in generation.registrations if registration.bundle_id}
        for record in records:
            record_path = record.path_clean or record.path
            record_bundle = record.bundle_id or record.identifier or record.canonical_id
            if record_path in paths or record_bundle in bundles:
                result[generation.generation_id].append(record)
    return result


def _ordered_unique(values: list[str]) -> list[str]:
    return sorted(set(values), key=lambda value: (0 if value.startswith("Observed: shared application UUID") else 1 if value.startswith("Observed: shared bundle identifier") else 2 if value.startswith("Observed: shared executable path") else 3 if value.startswith("Observed: shared Team ID") else 4, value))
