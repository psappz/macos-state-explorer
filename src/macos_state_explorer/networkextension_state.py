from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import plistlib
import re
from pathlib import Path
from typing import Any, Iterable

REFERENCE_TERMS = (
    "Chrome",
    "Chromium",
    "Edge",
    "GoogleUpdater",
    "SecurityPrivacyExtension",
    "System Settings",
    "LaunchServices",
)
UNKNOWN_OBSERVATIONS = (
    "NetworkExtension preference files",
    "Local Network preference stores",
    "per-app authorization records",
    "signing identities",
    "team identifiers",
    "application UUIDs",
    "preference generations",
    "application identity changes",
    "LaunchServices identities",
)
BUNDLE_ID_RE = re.compile(r"\b(?:com\.(?:google|microsoft|apple|chromium)[A-Za-z0-9_.-]+)\b")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
TEAM_ID_RE = re.compile(r"\b[A-Z0-9]{10}\b")


@dataclass(frozen=True)
class NetworkExtensionArtifact:
    path: str
    kind: str
    observed: bool
    observation_state: str
    size_bytes: int | None = None
    modified_time: float | None = None
    preference_generation: str | None = None
    bundle_ids: tuple[str, ...] = ()
    application_uuids: tuple[str, ...] = ()
    team_ids: tuple[str, ...] = ()
    references: dict[str, int] = field(default_factory=dict)
    parse_status: str = "Unknown"
    error: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "observed": self.observed,
            "observation_state": self.observation_state,
            "size_bytes": self.size_bytes,
            "modified_time": self.modified_time,
            "preference_generation": self.preference_generation,
            "bundle_ids": list(self.bundle_ids),
            "application_uuids": list(self.application_uuids),
            "team_ids": list(self.team_ids),
            "references": dict(self.references),
            "parse_status": self.parse_status,
            "error": self.error,
        }


@dataclass(frozen=True)
class NetworkExtensionObservation:
    name: str
    classification: str
    detail: str
    source: str

    def to_json_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "classification": self.classification,
            "detail": self.detail,
            "source": self.source,
        }


@dataclass(frozen=True)
class NetworkExtensionState:
    state_id: str
    artifacts: tuple[NetworkExtensionArtifact, ...]
    observations: tuple[NetworkExtensionObservation, ...]
    roots: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        artifact_paths = sorted(artifact.path for artifact in self.artifacts if artifact.observed)
        bundle_ids = sorted({item for artifact in self.artifacts for item in artifact.bundle_ids})
        application_uuids = sorted({item for artifact in self.artifacts for item in artifact.application_uuids})
        team_ids = sorted({item for artifact in self.artifacts for item in artifact.team_ids})
        references = {term: sum(artifact.references.get(term, 0) for artifact in self.artifacts) for term in REFERENCE_TERMS}
        unknown_items = sorted(observation.name for observation in self.observations if observation.classification == "Unknown")
        return {
            "artifact_count": len(artifact_paths),
            "observation_count": len(self.observations),
            "unknown_count": len(unknown_items),
            "artifact_paths": artifact_paths,
            "bundle_ids": bundle_ids,
            "application_uuids": application_uuids,
            "team_ids": team_ids,
            "references": references,
            "unknown_items": unknown_items,
            "read_only": True,
            "mutation_performed": False,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension state",
            "state_id": self.state_id,
            "timestamp": "1970-01-01T00:00:00Z",
            "read_only": True,
            "mutation_performed": False,
            "summary": self.summary(),
            "artifacts": [artifact.to_json_dict() for artifact in self.artifacts],
            "observations": [observation.to_json_dict() for observation in self.observations],
            "roots": list(self.roots),
        }


def default_networkextension_roots() -> list[Path]:
    home = Path.home()
    return [
        home / "Library" / "Preferences",
        Path("/Library/Preferences"),
        Path("/Library/Preferences/SystemConfiguration"),
        Path("/Library/Application Support/com.apple.TCC"),
    ]


def build_networkextension_state(roots: Iterable[Path] | None = None) -> NetworkExtensionState:
    root_paths = [Path(root).expanduser() for root in (roots if roots is not None else default_networkextension_roots())]
    artifacts = tuple(sorted(_discover_artifacts(root_paths), key=lambda artifact: artifact.path))
    observations = tuple(_build_observations(artifacts))
    digest = hashlib.sha256(
        "|".join(
            [artifact.path for artifact in artifacts]
            + [f"{observation.name}:{observation.classification}" for observation in observations]
        ).encode()
    ).hexdigest()[:16]
    return NetworkExtensionState(
        state_id=f"networkextension-state-{digest}",
        artifacts=artifacts,
        observations=observations,
        roots=tuple(str(root) for root in root_paths),
    )


def render_networkextension_state(state: NetworkExtensionState) -> str:
    summary = state.summary()
    lines = [
        "NetworkExtension state",
        "- Read-only: true",
        "- Mutation performed: false",
        f"- Observed artifacts: {summary['artifact_count']}",
        f"- Unknown observations: {summary['unknown_count']}",
        f"- Chrome references: {summary['references'].get('Chrome', 0)}",
        f"- Edge references: {summary['references'].get('Edge', 0)}",
        f"- GoogleUpdater references: {summary['references'].get('GoogleUpdater', 0)}",
        "",
        "Artifacts",
    ]
    if state.artifacts:
        for artifact in state.artifacts:
            lines.append(f"- {artifact.path} [{artifact.observation_state}, {artifact.parse_status}]")
    else:
        lines.append("- none observed")
    lines.extend(["", "Observations"])
    for observation in state.observations:
        lines.append(f"- {observation.name}: {observation.classification} — {observation.detail}")
    return "\n".join(lines)


def render_networkextension_state_summary(summary: dict[str, Any]) -> str:
    references_value = summary.get("references")
    refs = references_value if isinstance(references_value, dict) else {}
    bundle_ids_value = summary.get("bundle_ids")
    bundle_ids = bundle_ids_value if isinstance(bundle_ids_value, list) else []
    return "\n".join(
        [
            "NetworkExtension state",
            f"- Artifacts: {summary.get('artifact_count', 0)}",
            f"- Unknown observations: {summary.get('unknown_count', 0)}",
            f"- Chrome references: {refs.get('Chrome', 0)}",
            f"- Edge references: {refs.get('Edge', 0)}",
            f"- Bundle IDs: {', '.join(bundle_ids) if bundle_ids else 'none'}",
        ]
    )


def networkextension_state_summary(state: NetworkExtensionState) -> dict[str, Any]:
    return state.summary()


def _discover_artifacts(roots: list[Path]) -> list[NetworkExtensionArtifact]:
    artifacts: list[NetworkExtensionArtifact] = []
    for root in roots:
        if root.is_file():
            candidate_files = [root]
        elif root.is_dir():
            candidate_files = sorted(path for path in root.rglob("*") if path.is_file() and _is_candidate(path))
        else:
            candidate_files = []
        for path in candidate_files:
            artifacts.append(_read_artifact(path, root))
    return artifacts


def _is_candidate(path: Path) -> bool:
    lower = str(path).lower()
    return any(
        token in lower
        for token in [
            "networkextension",
            "localnetwork",
            "local-network",
            "securityprivacyextension",
            "systemsettings",
        ]
    )


def _read_artifact(path: Path, root: Path) -> NetworkExtensionArtifact:
    try:
        data = path.read_bytes()
        text = _decode_artifact(path, data)
        stat = path.stat()
        return NetworkExtensionArtifact(
            path=_display_path(path, root),
            kind=_artifact_kind(path),
            observed=True,
            observation_state="Observed",
            size_bytes=stat.st_size,
            modified_time=stat.st_mtime,
            preference_generation=_preference_generation(text),
            bundle_ids=tuple(sorted(set(BUNDLE_ID_RE.findall(text)))),
            application_uuids=tuple(sorted(set(UUID_RE.findall(text)))),
            team_ids=tuple(sorted(set(TEAM_ID_RE.findall(text)) - {uuid.split("-")[0].upper() for uuid in UUID_RE.findall(text)})),
            references={term: _count_reference(text, term) for term in REFERENCE_TERMS},
            parse_status="Observed" if text else "Unknown",
        )
    except Exception as exc:  # pragma: no cover - defensive for unreadable system files
        return NetworkExtensionArtifact(
            path=_display_path(path, root),
            kind=_artifact_kind(path),
            observed=False,
            observation_state="Unknown",
            references={term: 0 for term in REFERENCE_TERMS},
            parse_status="Unknown",
            error=type(exc).__name__,
        )


def _decode_artifact(path: Path, data: bytes) -> str:
    if path.suffix == ".plist":
        try:
            parsed = plistlib.loads(data)
            return json.dumps(parsed, sort_keys=True, default=str)
        except Exception:
            pass
    return data.decode("utf-8", errors="ignore")


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _artifact_kind(path: Path) -> str:
    lower = path.name.lower()
    if "localnetwork" in lower or "local-network" in lower:
        return "Local Network preference store"
    if "networkextension" in lower:
        return "NetworkExtension preference file"
    if "securityprivacyextension" in lower:
        return "SecurityPrivacyExtension reference"
    return "Related preference artifact"


def _preference_generation(text: str) -> str | None:
    match = re.search(r"\b(?:generation|Generation)\b[^0-9]{0,12}(\d+)", text)
    return match.group(1) if match else None


def _count_reference(text: str, term: str) -> int:
    if term == "System Settings":
        return len(re.findall(r"System Settings|SystemSettings", text, flags=re.IGNORECASE))
    if term in {"Chrome", "Chromium", "Edge"}:
        return len(re.findall(rf"(?<![.A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_-])", text, flags=re.IGNORECASE))
    return len(re.findall(re.escape(term), text, flags=re.IGNORECASE))


def _build_observations(artifacts: tuple[NetworkExtensionArtifact, ...]) -> list[NetworkExtensionObservation]:
    summary_artifacts = [artifact for artifact in artifacts if artifact.observed]
    bundle_ids = sorted({item for artifact in artifacts for item in artifact.bundle_ids})
    uuids = sorted({item for artifact in artifacts for item in artifact.application_uuids})
    team_ids = sorted({item for artifact in artifacts for item in artifact.team_ids})
    generations = sorted({artifact.preference_generation for artifact in artifacts if artifact.preference_generation})
    observations = [
        _obs("NetworkExtension preference files", bool(summary_artifacts), f"{len(summary_artifacts)} candidate artifact(s) observed"),
        _obs("Local Network preference stores", any("Local Network" in artifact.kind for artifact in artifacts), "Local Network preference-store artifact observed"),
        _obs("per-app authorization records", bool(bundle_ids), f"Bundle identifiers: {', '.join(bundle_ids) if bundle_ids else 'none'}"),
        _obs("bundle identifiers", bool(bundle_ids), f"{len(bundle_ids)} bundle identifier(s) observed"),
        _obs("application UUIDs", bool(uuids), f"{len(uuids)} application UUID(s) observed"),
        _obs("signing identities", False, "Code signing identities require separate code-signing inspection and are not inferred from preferences"),
        _obs("team identifiers", bool(team_ids), f"{len(team_ids)} team identifier(s) observed"),
        _obs("preference timestamps", bool(summary_artifacts), "File modification timestamps recorded for observed artifacts"),
        _obs("preference generations", bool(generations), f"Generations: {', '.join(generations) if generations else 'none'}"),
        _obs("application identity changes", False, "Identity changes require a prior state comparison and are not inferred from one snapshot"),
        _obs("application path associations", any("/Applications/" in _artifact_text_hint(artifact) for artifact in artifacts), "Application paths observed in preference text when present"),
        _obs("LaunchServices identities", any(artifact.references.get("LaunchServices", 0) for artifact in artifacts), "LaunchServices references observed in preference text"),
    ]
    return observations


def _obs(name: str, observed: bool, detail: str) -> NetworkExtensionObservation:
    return NetworkExtensionObservation(name=name, classification="Observed" if observed else "Unknown", detail=detail, source="NetworkExtension preference observation")


def _artifact_text_hint(artifact: NetworkExtensionArtifact) -> str:
    return " ".join([artifact.path, *artifact.bundle_ids])
