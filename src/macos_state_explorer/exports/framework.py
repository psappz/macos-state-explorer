from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class EvidenceBundleExportRequest:
    audience: str
    target: str
    issue: str
    output: Path

    def normalized(self) -> "EvidenceBundleExportRequest":
        return EvidenceBundleExportRequest(
            audience=_normalize_key(self.audience),
            target=_normalize_key(self.target),
            issue=_normalize_key(self.issue),
            output=self.output.expanduser(),
        )


@dataclass(frozen=True)
class EvidenceBundleExport:
    manifest: dict[str, Any]
    output: Path


class EvidenceBundleProvider(Protocol):
    def export(self, request: EvidenceBundleExportRequest) -> EvidenceBundleExport: ...


@dataclass
class EvidenceBundleRegistry:
    _providers: dict[tuple[str, str, str], EvidenceBundleProvider] = field(default_factory=dict)

    def register(
        self,
        *,
        audience: str,
        target: str,
        issue: str,
        provider: EvidenceBundleProvider,
    ) -> None:
        self._providers[(_normalize_key(audience), _normalize_key(target), _normalize_key(issue))] = provider

    def provider_for(self, request: EvidenceBundleExportRequest) -> EvidenceBundleProvider:
        normalized = request.normalized()
        key = (normalized.audience, normalized.target, normalized.issue)
        provider = self._providers.get(key)
        if provider is None:
            supported = ", ".join("/".join(parts) for parts in sorted(self._providers)) or "none"
            requested = "/".join(key)
            raise ValueError(
                "No evidence export provider registered for "
                f"{requested}. Supported combinations: {supported}."
            )
        return provider


def export_evidence_bundle(
    request: EvidenceBundleExportRequest,
    *,
    registry: EvidenceBundleRegistry,
) -> EvidenceBundleExport:
    normalized = request.normalized()
    provider = registry.provider_for(normalized)
    prepare_export_output(normalized.output)
    export = provider.export(normalized)
    write_manifest(export.output / "manifest.json", export.manifest)
    return export


def prepare_export_output(output: Path) -> Path:
    output = output.expanduser()
    if output.is_symlink():
        raise ValueError("Export output path must not be a symlink")
    if output.exists() and not output.is_dir():
        raise ValueError("Export output path exists and is not a directory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Export output directory already exists and is not empty")
    output.mkdir(parents=True, exist_ok=True)
    return output


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def artifact_entry(path: str, *, description: str, media_type: str) -> dict[str, str]:
    return {"path": path, "description": description, "media_type": media_type}


def _normalize_key(value: str) -> str:
    return value.strip().lower()
