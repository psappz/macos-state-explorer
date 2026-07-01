from __future__ import annotations

from macos_state_explorer.launchservices.canonical import find_preferred_registration
from macos_state_explorer.launchservices.grouping import BundleGroup
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


def record(
    *,
    sequence_number: int | None = None,
    registration_date: str | None = None,
    path_exists: bool | None = None,
    classification: LaunchServicesStatus = LaunchServicesStatus.UNKNOWN,
    version: str | None = None,
) -> LaunchServicesRecord:
    return LaunchServicesRecord(
        raw_block="raw",
        bundle_id="com.example.App",
        sequence_number=sequence_number,
        registration_date=registration_date,
        path_exists=path_exists,
        classification=classification,
        version=version,
    )


def group(*records: LaunchServicesRecord) -> BundleGroup:
    return BundleGroup(bundle_id="com.example.App", records=list(records))


def test_sequence_number_is_primary_signal():
    older_missing = record(
        sequence_number=20,
        registration_date="2020-01-01 00:00:00 +0000",
        path_exists=False,
        classification=LaunchServicesStatus.STALE,
        version="1.0",
    )
    newer_active = record(
        sequence_number=10,
        registration_date="2026-01-01 00:00:00 +0000",
        path_exists=True,
        classification=LaunchServicesStatus.ACTIVE,
        version="9.0",
    )

    preferred = find_preferred_registration(group(newer_active, older_missing))

    assert preferred.record == older_missing
    assert preferred.score == 3
    assert preferred.confidence >= 0.55
    assert "sequence number" in preferred.reason


def test_registration_date_breaks_sequence_ties():
    older = record(sequence_number=10, registration_date="2025-01-01 00:00:00 +0000", version="9.0")
    newer = record(sequence_number=10, registration_date="2026-01-01 00:00:00 +0000", version="1.0")

    preferred = find_preferred_registration(group(older, newer))

    assert preferred.record == newer
    assert "2026-01-01" in preferred.reason


def test_existing_path_breaks_date_ties():
    missing = record(sequence_number=10, registration_date="2026-01-01 00:00:00 +0000", path_exists=False)
    existing = record(sequence_number=10, registration_date="2026-01-01 00:00:00 +0000", path_exists=True)

    preferred = find_preferred_registration(group(missing, existing))

    assert preferred.record == existing
    assert "path exists" in preferred.reason


def test_active_status_breaks_path_ties():
    stale = record(
        sequence_number=10,
        registration_date="2026-01-01 00:00:00 +0000",
        path_exists=True,
        classification=LaunchServicesStatus.STALE,
        version="9.0",
    )
    active = record(
        sequence_number=10,
        registration_date="2026-01-01 00:00:00 +0000",
        path_exists=True,
        classification=LaunchServicesStatus.ACTIVE,
        version="1.0",
    )

    preferred = find_preferred_registration(group(stale, active))

    assert preferred.record == active
    assert LaunchServicesStatus.ACTIVE.value in preferred.reason


def test_highest_version_breaks_active_ties():
    lower = record(
        sequence_number=10,
        registration_date="2026-01-01 00:00:00 +0000",
        path_exists=True,
        classification=LaunchServicesStatus.ACTIVE,
        version="1.9",
    )
    higher = record(
        sequence_number=10,
        registration_date="2026-01-01 00:00:00 +0000",
        path_exists=True,
        classification=LaunchServicesStatus.ACTIVE,
        version="1.10",
    )

    preferred = find_preferred_registration(group(lower, higher))

    assert preferred.record == higher
    assert "1.10" in preferred.reason
    assert preferred.score == 5


def test_empty_group_returns_no_preference():
    preferred = find_preferred_registration(BundleGroup(bundle_id="com.example.Empty"))

    assert preferred.record is None
    assert preferred.score == 0
    assert preferred.confidence == 0
    assert "No LaunchServices records" in preferred.reason
