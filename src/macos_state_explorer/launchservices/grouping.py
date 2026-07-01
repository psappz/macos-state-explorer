from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from pydantic import BaseModel, Field

MISSING_BUNDLE_ID = "<missing>"


class BundleGroup(BaseModel):
    bundle_id: str | None = None
    display_name: str | None = None
    records: list[LaunchServicesRecord] = Field(default_factory=list)
    versions: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    registrations: list[str] = Field(default_factory=list)
    statuses: list[LaunchServicesStatus] = Field(default_factory=list)


def group_records(records: Iterable[LaunchServicesRecord]) -> dict[str, BundleGroup]:
    groups: dict[str, BundleGroup] = {}

    for record in records:
        key = record.bundle_id or MISSING_BUNDLE_ID
        group = groups.setdefault(key, BundleGroup(bundle_id=record.bundle_id))
        group.records.append(record)

    for group in groups.values():
        group.records.sort(key=_record_sort_key, reverse=True)
        group.display_name = _first_value(
            record.display_name or record.name or record.bundle_id for record in group.records
        )
        group.versions = _unique_values(record.version for record in group.records)
        group.paths = _unique_values((record.path_clean or record.path) for record in group.records)
        group.registrations = _unique_values(record.registration_date for record in group.records)
        group.statuses = _unique_values(record.classification for record in group.records)

    return groups


def bundle_statistics(records: Iterable[LaunchServicesRecord]) -> dict[str, Any]:
    record_list = list(records)
    groups = group_records(record_list)
    path_counts = Counter(record.path_clean or record.path for record in record_list if record.path_clean or record.path)
    status_counts = Counter(record.classification for record in record_list)
    volume_counts = Counter(record.volume or MISSING_BUNDLE_ID for record in record_list)

    duplicate_versions: dict[str, dict[str, int]] = {}
    for key, group in groups.items():
        version_counts = Counter(record.version for record in group.records if record.version)
        duplicates = {version: count for version, count in version_counts.items() if count > 1}
        if duplicates:
            duplicate_versions[key] = duplicates

    return {
        "total_bundles": len(groups),
        "duplicate_bundle_ids": sorted(
            key for key, group in groups.items() if key != MISSING_BUNDLE_ID and len(group.records) > 1
        ),
        "duplicate_paths": {path: count for path, count in sorted(path_counts.items()) if count > 1},
        "duplicate_versions": duplicate_versions,
        "status_counts": dict(sorted(status_counts.items())),
        "volume_counts": dict(sorted(volume_counts.items())),
    }


def classification_counts(records: Iterable[LaunchServicesRecord]) -> dict[LaunchServicesStatus, int]:
    counts: dict[LaunchServicesStatus, int] = {}
    for record in records:
        counts[record.classification] = counts.get(record.classification, 0) + 1
    return counts


def stale_records(records: Iterable[LaunchServicesRecord]) -> list[LaunchServicesRecord]:
    stale_classifications = {
        LaunchServicesStatus.ORPHANED,
        LaunchServicesStatus.STALE,
        LaunchServicesStatus.MISSING_VOLUME,
    }
    return [record for record in records if record.classification in stale_classifications]


def _record_sort_key(record: LaunchServicesRecord) -> tuple[datetime, tuple[tuple[int, int, str], ...]]:
    return (_parse_registration_date(record.registration_date), _version_key(record.version))


def _parse_registration_date(value: str | None) -> datetime:
    if not value:
        return datetime.min

    for date_format in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, date_format)
            return parsed.replace(tzinfo=None)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def _version_key(value: str | None) -> tuple[tuple[int, int, str], ...]:
    if not value:
        return ()

    parts: list[tuple[int, int, str]] = []
    for part in value.replace("-", ".").split("."):
        if part.isdecimal():
            parts.append((1, int(part), ""))
        else:
            parts.append((0, 0, part))
    return tuple(parts)


def _first_value(values: Iterable[str | None]) -> str | None:
    return next((value for value in values if value), None)


def _unique_values(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique
