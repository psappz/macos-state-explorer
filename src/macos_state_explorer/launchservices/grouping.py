from __future__ import annotations

from collections.abc import Iterable

from macos_state_explorer.launchservices.models import LaunchServicesRecord


def classification_counts(records: Iterable[LaunchServicesRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.classification] = counts.get(record.classification, 0) + 1
    return counts


def stale_records(records: Iterable[LaunchServicesRecord]) -> list[LaunchServicesRecord]:
    stale_classifications = {"ORPHANED", "STALE", "MISSING_VOLUME"}
    return [record for record in records if record.classification in stale_classifications]
