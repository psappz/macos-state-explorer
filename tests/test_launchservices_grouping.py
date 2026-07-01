from __future__ import annotations

from macos_state_explorer.launchservices.grouping import MISSING_BUNDLE_ID, bundle_statistics, group_records
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


def record(
    bundle_id: str | None,
    *,
    display_name: str | None = None,
    version: str | None = None,
    path: str | None = None,
    registration_date: str | None = None,
    classification: LaunchServicesStatus = LaunchServicesStatus.ACTIVE,
    volume: str | None = "/",
) -> LaunchServicesRecord:
    return LaunchServicesRecord(
        raw_block="raw",
        bundle_id=bundle_id,
        display_name=display_name,
        version=version,
        path_clean=path,
        registration_date=registration_date,
        classification=classification,
        volume=volume,
    )


def test_group_records_sorts_multiple_versions_newest_first():
    records = [
        record("com.example.App", version="1.0", registration_date="2025-01-01 00:00:00 +0000"),
        record("com.example.App", version="3.0", registration_date="2026-01-01 00:00:00 +0000"),
        record("com.example.App", version="2.0", registration_date="2026-01-01 00:00:00 +0000"),
    ]

    groups = group_records(records)
    group = groups["com.example.App"]

    assert [item.version for item in group.records] == ["3.0", "2.0", "1.0"]
    assert group.versions == ["3.0", "2.0", "1.0"]
    assert group.registrations == ["2026-01-01 00:00:00 +0000", "2025-01-01 00:00:00 +0000"]


def test_group_records_collects_multiple_paths_and_statuses():
    records = [
        record("com.example.App", display_name="Example", path="/Applications/Example.app"),
        record(
            "com.example.App",
            path="/Volumes/External/Example.app",
            classification=LaunchServicesStatus.MISSING_VOLUME,
        ),
    ]

    group = group_records(records)["com.example.App"]

    assert group.display_name == "Example"
    assert group.paths == ["/Applications/Example.app", "/Volumes/External/Example.app"]
    assert group.statuses == [LaunchServicesStatus.ACTIVE, LaunchServicesStatus.MISSING_VOLUME]


def test_group_records_keeps_missing_bundle_ids():
    records = [
        record(None, version="1.0", path="/Applications/Unknown.app"),
        record(None, version="2.0", path="/Applications/Other.app"),
    ]

    groups = group_records(records)

    assert list(groups) == [MISSING_BUNDLE_ID]
    assert groups[MISSING_BUNDLE_ID].bundle_id is None
    assert len(groups[MISSING_BUNDLE_ID].records) == 2


def test_bundle_statistics_reports_duplicates_and_counts():
    records = [
        record(
            "com.example.App",
            version="1.0",
            path="/Applications/Example.app",
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "com.example.App",
            version="1.0",
            path="/Applications/Example.app",
            classification=LaunchServicesStatus.STALE,
        ),
        record("com.example.Other", version="2.0", path="/Applications/Other.app", volume="/Volumes/External"),
        record(
            None,
            version="3.0",
            path="/Applications/MissingId.app",
            classification=LaunchServicesStatus.UNKNOWN,
            volume=None,
        ),
    ]

    stats = bundle_statistics(records)

    assert stats["total_bundles"] == 3
    assert stats["duplicate_bundle_ids"] == ["com.example.App"]
    assert stats["duplicate_paths"] == {"/Applications/Example.app": 2}
    assert stats["duplicate_versions"] == {"com.example.App": {"1.0": 2}}
    assert stats["status_counts"] == {
        LaunchServicesStatus.ACTIVE: 2,
        LaunchServicesStatus.STALE: 1,
        LaunchServicesStatus.UNKNOWN: 1,
    }
    assert stats["volume_counts"] == {"/": 2, "/Volumes/External": 1, MISSING_BUNDLE_ID: 1}
