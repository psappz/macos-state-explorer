from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


class GenerationClassification(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    MISSING = "MISSING"
    TRASH = "TRASH"
    MOUNTED_INSTALLER = "MOUNTED_INSTALLER"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GenerationRegistration:
    path: str | None
    bundle_id: str | None
    name: str | None
    version: str | None
    role: str
    generation_id: str
    classification: str
    exists_on_disk: bool | None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bundle_id": self.bundle_id,
            "name": self.name,
            "version": self.version,
            "role": self.role,
            "generation_id": self.generation_id,
            "classification": self.classification,
            "exists_on_disk": self.exists_on_disk,
        }


@dataclass(frozen=True)
class Generation:
    product_family: str
    vendor: str
    bundle_identifier: str | None
    generation_id: str
    version: str | None
    installation_root: str | None
    registrations: list[GenerationRegistration]
    helper_registrations: list[GenerationRegistration]
    framework_registrations: list[GenerationRegistration]
    updater_registrations: list[GenerationRegistration]
    mounted_volume_registrations: list[GenerationRegistration]
    trash_registrations: list[GenerationRegistration]
    exists: bool | None
    active: bool
    stale: bool
    classification: GenerationClassification
    confidence: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "product_family": self.product_family,
            "vendor": self.vendor,
            "bundle_identifier": self.bundle_identifier,
            "generation_id": self.generation_id,
            "version": self.version,
            "installation_root": self.installation_root,
            "classification": self.classification.value,
            "exists": self.exists,
            "active": self.active,
            "stale": self.stale,
            "confidence": round(self.confidence, 4),
            "registration_count": len(self.registrations),
            "helper_registration_count": len(self.helper_registrations),
            "framework_registration_count": len(self.framework_registrations),
            "updater_registration_count": len(self.updater_registrations),
            "mounted_volume_registration_count": len(self.mounted_volume_registrations),
            "trash_registration_count": len(self.trash_registrations),
            "registrations": [registration.to_json_dict() for registration in self.registrations],
        }


@dataclass(frozen=True)
class GenerationAnalysis:
    generations: list[Generation]
    registrations: list[GenerationRegistration]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "launchservices generations",
            "generation_count": len(self.generations),
            "generations": [generation.to_json_dict() for generation in self.generations],
            "registrations": [registration.to_json_dict() for registration in self.registrations],
            "summary": generation_summary(self),
        }


def analyze_generations(records: Iterable[LaunchServicesRecord | dict[str, Any]]) -> GenerationAnalysis:
    normalized = [_record_from_value(record) for record in records]
    grouped: dict[tuple[str, str | None, str | None], list[LaunchServicesRecord]] = {}
    metadata: dict[tuple[str, str | None, str | None], tuple[str, str, str | None]] = {}
    for record in normalized:
        product = _detect_product(record)
        if product is None:
            continue
        product_family, vendor = product
        version = _detect_version(record)
        root = _installation_root(record, product_family)
        generation_id = _generation_id(product_family, version, root)
        key = (product_family, version, root)
        grouped.setdefault(key, []).append(record)
        metadata[key] = (vendor, generation_id, record.bundle_id)

    generations: list[Generation] = []
    registrations: list[GenerationRegistration] = []
    for key, records_for_generation in grouped.items():
        product_family, version, root = key
        vendor, generation_id, bundle_identifier = metadata[key]
        generation_registrations = [
            GenerationRegistration(
                path=record.path_clean or record.path,
                bundle_id=record.bundle_id or record.identifier or record.canonical_id,
                name=record.display_name or record.name,
                version=_detect_version(record),
                role=_registration_role(record),
                generation_id=generation_id,
                classification=str(record.classification.value if hasattr(record.classification, "value") else record.classification),
                exists_on_disk=record.path_exists,
            )
            for record in records_for_generation
        ]
        generation = _build_generation(
            product_family=product_family,
            vendor=vendor,
            bundle_identifier=bundle_identifier,
            generation_id=generation_id,
            version=version,
            root=root,
            registrations=generation_registrations,
            source_records=records_for_generation,
        )
        generations.append(generation)
        registrations.extend(generation_registrations)

    generations.sort(key=lambda generation: (generation.product_family, _classification_order(generation.classification), _version_key(generation.version), generation.installation_root or ""))
    registrations.sort(key=lambda registration: (registration.generation_id, registration.path or ""))
    return GenerationAnalysis(generations=generations, registrations=registrations)


def render_generation_summary(analysis: GenerationAnalysis) -> str:
    lines = ["LaunchServices generation analysis"]
    if not analysis.generations:
        return "\n".join([*lines, "", "No Chromium-family LaunchServices generations detected."])
    by_product: dict[str, list[Generation]] = {}
    for generation in analysis.generations:
        by_product.setdefault(generation.product_family, []).append(generation)
    for product in sorted(by_product):
        generations = by_product[product]
        lines.extend(["", product, "-" * len(product)])
        active = [g for g in generations if g.classification == GenerationClassification.ACTIVE]
        stale = [g for g in generations if g.classification == GenerationClassification.STALE]
        mounted = [g for g in generations if g.classification == GenerationClassification.MOUNTED_INSTALLER]
        trash = [g for g in generations if g.classification == GenerationClassification.TRASH]
        other = [g for g in generations if g.classification not in {GenerationClassification.ACTIVE, GenerationClassification.STALE, GenerationClassification.MOUNTED_INSTALLER, GenerationClassification.TRASH}]
        _append_section(lines, "Active generation", active)
        _append_section(lines, "Older generations", stale)
        _append_section(lines, "Mounted installer", mounted)
        _append_section(lines, "Trash", trash)
        if other:
            _append_section(lines, "Other generations", other)
    return "\n".join(lines)


def generation_summary(analysis: GenerationAnalysis) -> dict[str, Any]:
    counts = Counter(generation.classification for generation in analysis.generations)
    by_product: dict[str, dict[str, int]] = {}
    for generation in analysis.generations:
        product = by_product.setdefault(
            generation.product_family,
            {
                "active_generation_count": 0,
                "obsolete_generation_count": 0,
                "mounted_installer_generation_count": 0,
                "trash_generation_count": 0,
                "missing_generation_count": 0,
                "partial_generation_count": 0,
                "unknown_generation_count": 0,
            },
        )
        if generation.classification == GenerationClassification.ACTIVE:
            product["active_generation_count"] += 1
        elif generation.classification == GenerationClassification.STALE:
            product["obsolete_generation_count"] += 1
        elif generation.classification == GenerationClassification.MOUNTED_INSTALLER:
            product["mounted_installer_generation_count"] += 1
        elif generation.classification == GenerationClassification.TRASH:
            product["trash_generation_count"] += 1
        elif generation.classification == GenerationClassification.MISSING:
            product["missing_generation_count"] += 1
        elif generation.classification == GenerationClassification.PARTIAL:
            product["partial_generation_count"] += 1
        else:
            product["unknown_generation_count"] += 1
    return {
        "active_generation_count": counts[GenerationClassification.ACTIVE],
        "obsolete_generation_count": counts[GenerationClassification.STALE],
        "mounted_installer_generation_count": counts[GenerationClassification.MOUNTED_INSTALLER],
        "trash_generation_count": counts[GenerationClassification.TRASH],
        "missing_generation_count": counts[GenerationClassification.MISSING],
        "partial_generation_count": counts[GenerationClassification.PARTIAL],
        "unknown_generation_count": counts[GenerationClassification.UNKNOWN],
        "products": by_product,
    }


def summarize_chromium_generations_for_local_network(analysis: GenerationAnalysis) -> str:
    if not analysis.generations:
        return "Chromium-family generations: none detected."
    lines: list[str] = []
    for product, counts in sorted(generation_summary(analysis)["products"].items()):
        parts: list[str] = []
        if counts["obsolete_generation_count"]:
            parts.append(_count_phrase(counts["obsolete_generation_count"], "obsolete generation"))
        if counts["mounted_installer_generation_count"]:
            parts.append(_count_phrase(counts["mounted_installer_generation_count"], "mounted installer generation"))
        if counts["trash_generation_count"]:
            parts.append(_count_phrase(counts["trash_generation_count"], "Trash generation"))
        if parts:
            lines.append(f"{product}: " + ", ".join(parts))
    return "\n".join(lines) if lines else "Chromium-family generations: no obsolete, mounted installer, or Trash generations detected."


def _record_from_value(value: LaunchServicesRecord | dict[str, Any]) -> LaunchServicesRecord:
    if isinstance(value, LaunchServicesRecord):
        return value
    data = dict(value)
    data.setdefault("raw_block", str(value))
    return LaunchServicesRecord(**data)


def _build_generation(
    *,
    product_family: str,
    vendor: str,
    bundle_identifier: str | None,
    generation_id: str,
    version: str | None,
    root: str | None,
    registrations: list[GenerationRegistration],
    source_records: list[LaunchServicesRecord],
) -> Generation:
    helpers = [registration for registration in registrations if registration.role == "helper"]
    frameworks = [registration for registration in registrations if registration.role == "framework"]
    updaters = [registration for registration in registrations if registration.role == "updater"]
    mounted = [registration for registration, record in zip(registrations, source_records, strict=True) if _is_mounted_volume(record)]
    trash = [registration for registration in registrations if _is_trash_path(registration.path)]
    exists_values = [record.path_exists for record in source_records if record.path_exists is not None]
    exists = any(exists_values) if exists_values else None
    active = any(record.classification == LaunchServicesStatus.ACTIVE and record.path_exists is True for record in source_records)
    classification = _generation_classification(source_records, active=active, trash=bool(trash), mounted=bool(mounted), exists=exists)
    stale = classification in {GenerationClassification.STALE, GenerationClassification.MISSING, GenerationClassification.TRASH, GenerationClassification.MOUNTED_INSTALLER, GenerationClassification.PARTIAL}
    return Generation(
        product_family=product_family,
        vendor=vendor,
        bundle_identifier=bundle_identifier,
        generation_id=generation_id,
        version=version,
        installation_root=root,
        registrations=registrations,
        helper_registrations=helpers,
        framework_registrations=frameworks,
        updater_registrations=updaters,
        mounted_volume_registrations=mounted,
        trash_registrations=trash,
        exists=exists,
        active=active,
        stale=stale,
        classification=classification,
        confidence=0.92 if version and root else 0.72,
    )


def _generation_classification(
    records: list[LaunchServicesRecord],
    *,
    active: bool,
    trash: bool,
    mounted: bool,
    exists: bool | None,
) -> GenerationClassification:
    if trash:
        return GenerationClassification.TRASH
    if mounted:
        return GenerationClassification.MOUNTED_INSTALLER
    if active:
        return GenerationClassification.ACTIVE
    if any(record.classification in {LaunchServicesStatus.STALE, LaunchServicesStatus.ORPHANED, LaunchServicesStatus.DUPLICATE, LaunchServicesStatus.SUPERSEDED, LaunchServicesStatus.SHADOWED} for record in records):
        return GenerationClassification.STALE
    if exists is False or any(record.volume_exists is False or record.classification == LaunchServicesStatus.MISSING_VOLUME for record in records):
        return GenerationClassification.MISSING
    if any(record.path_exists is True for record in records) and any(record.path_exists is False for record in records):
        return GenerationClassification.PARTIAL
    return GenerationClassification.UNKNOWN


def _detect_product(record: LaunchServicesRecord) -> tuple[str, str] | None:
    bundle_id = (record.bundle_id or record.identifier or record.canonical_id or "").lower()
    name = " ".join(str(part or "") for part in [record.name, record.display_name]).lower()
    path = (record.path_clean or record.path or "").lower()
    text = " ".join([bundle_id, name, path])

    if _is_ios_placeholder(record):
        return None
    if "edgeupdater" in text or bundle_id.startswith("com.microsoft.edgeupdater"):
        return ("EdgeUpdater", "Microsoft")
    if "googleupdater" in text or bundle_id.startswith("com.google.googleupdater"):
        return ("GoogleUpdater", "Google")
    if _is_google_chrome_identity(bundle_id, name, path):
        return ("Google Chrome", "Google")
    if _is_microsoft_edge_identity(bundle_id, name, path):
        return ("Microsoft Edge", "Microsoft")
    if bundle_id.startswith("com.brave.browser") or "/brave browser.app" in path or "brave browser" in name:
        return ("Brave", "Brave")
    if bundle_id.startswith("company.thebrowser.browser") or "/arc.app" in path or "arc helper" in name:
        return ("Arc", "The Browser Company")
    if bundle_id.startswith("org.chromium.chromium") or "/chromium.app" in path or name == "chromium":
        return ("Chromium", "Chromium")
    return None


def _is_google_chrome_identity(bundle_id: str, name: str, path: str) -> bool:
    if bundle_id.startswith("com.google.chrome"):
        return True
    chrome_path_markers = (
        "/google chrome.app",
        "/google chrome framework.framework",
        "/google chrome helper",
    )
    if any(marker in path for marker in chrome_path_markers):
        return True
    return name in {"google chrome", "google chrome helper", "google chrome framework"} or name.startswith("google chrome helper")


def _is_microsoft_edge_identity(bundle_id: str, name: str, path: str) -> bool:
    if bundle_id.startswith("com.microsoft.edgemac") or bundle_id.startswith("com.microsoft.edge.") or bundle_id == "com.microsoft.edge":
        return True
    edge_path_markers = (
        "/microsoft edge.app",
        "/microsoft edge framework.framework",
        "/microsoft edge helper",
    )
    if any(marker in path for marker in edge_path_markers):
        return True
    return name in {"microsoft edge", "microsoft edge helper", "microsoft edge framework"} or name.startswith("microsoft edge helper")


def _is_ios_placeholder(record: LaunchServicesRecord) -> bool:
    platform = (record.platform or "").lower()
    path = (record.path_clean or record.path or "").lower()
    bundle_id = (record.bundle_id or record.identifier or record.canonical_id or "").lower()
    if platform in {"ios", "iphoneos", "watchos", "tvos"}:
        return True
    if "coresimulator" in path or "iosplaceholder" in path or "/mobile applications/" in path:
        return True
    return bundle_id.startswith("com.google.ios.") or bundle_id.startswith("com.apple.mobile")


def _detect_version(record: LaunchServicesRecord) -> str | None:
    for value in (record.display_version, record.version):
        if value:
            return value
    path = record.path_clean or record.path or ""
    match = re.search(r"/Versions/([^/]+)", path)
    if match:
        return match.group(1)
    return None


def _installation_root(record: LaunchServicesRecord, product_family: str) -> str | None:
    path = record.path_clean or record.path
    if not path:
        return None
    app_name = {
        "Google Chrome": "Google Chrome.app",
        "GoogleUpdater": "GoogleUpdater.app",
        "Microsoft Edge": "Microsoft Edge.app",
        "EdgeUpdater": "EdgeUpdater.app",
        "Chromium": "Chromium.app",
        "Brave": "Brave Browser.app",
        "Arc": "Arc.app",
    }[product_family]
    marker = f"/{app_name}"
    if marker in path:
        return path[: path.index(marker) + len(marker)]
    app_match = re.search(r"^(.+?\.app)(?:/|$)", path)
    if app_match:
        return app_match.group(1)
    framework_match = re.search(r"^(.+?\.framework)(?:/|$)", path)
    if framework_match:
        return framework_match.group(1)
    return path


def _registration_role(record: LaunchServicesRecord) -> str:
    text = " ".join(str(part or "") for part in [record.bundle_id, record.name, record.display_name, record.path, record.path_clean]).lower()
    if "updater" in text:
        return "updater"
    if "helper" in text or "renderer" in text or "gpu" in text or "alerts" in text:
        return "helper"
    if "framework" in text:
        return "framework"
    return "application"


def _generation_id(product_family: str, version: str | None, root: str | None) -> str:
    return f"{_slug(product_family)}:{version or 'unknown'}:{_slug(root or 'unknown-root')}"


def _slug(value: str) -> str:
    value = value.strip().lower().replace("/.trash/", "/trash/")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "unknown"


def _is_mounted_volume(record: LaunchServicesRecord) -> bool:
    path = record.path_clean or record.path or ""
    return (record.volume or "").startswith("/Volumes/") and record.volume_exists is True or path.startswith("/Volumes/") and record.volume_exists is not False


def _is_trash_path(path: str | None) -> bool:
    text = (path or "").lower().replace("\\", "/")
    return "/.trash/" in text or "/trash/" in text


def _classification_order(classification: GenerationClassification) -> int:
    return {
        GenerationClassification.ACTIVE: 0,
        GenerationClassification.STALE: 1,
        GenerationClassification.MOUNTED_INSTALLER: 2,
        GenerationClassification.TRASH: 3,
        GenerationClassification.MISSING: 4,
        GenerationClassification.PARTIAL: 5,
        GenerationClassification.UNKNOWN: 6,
    }[classification]


def _version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    parts: list[int] = []
    for part in value.replace("-", ".").split("."):
        if part.isdecimal():
            parts.append(int(part))
        else:
            break
    return tuple(parts)


def _append_section(lines: list[str], title: str, generations: list[Generation]) -> None:
    if not generations:
        return
    lines.append(title)
    for generation in sorted(generations, key=lambda item: _version_key(item.version)):
        noun = "registration" if len(generation.registrations) == 1 else "registrations"
        lines.append(f"  {generation.version or '<unknown>'}")
        lines.append(f"  {len(generation.registrations)} {noun}")


def _count_phrase(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"
