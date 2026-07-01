from __future__ import annotations

from typing import Any

from macos_state_explorer.launchservices.models import LaunchServicesStatus


def classify_record(values: dict[str, Any]) -> LaunchServicesStatus:
    if values.get("node_not_found") and values.get("path_exists") is False:
        return LaunchServicesStatus.ORPHANED
    if values.get("volume_exists") is False:
        return LaunchServicesStatus.MISSING_VOLUME
    if values.get("path_exists") is False:
        return LaunchServicesStatus.STALE
    if values.get("path_exists") is True:
        return LaunchServicesStatus.ACTIVE
    return LaunchServicesStatus.UNKNOWN
