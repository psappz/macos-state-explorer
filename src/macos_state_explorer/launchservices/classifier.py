from __future__ import annotations

from typing import Any

ACTIVE = "ACTIVE"
STALE = "STALE"
ORPHANED = "ORPHANED"
MISSING_VOLUME = "MISSING_VOLUME"
UNKNOWN = "UNKNOWN"

def classify_record(values: dict[str, Any]) -> str:
    if values.get("node_not_found") and values.get("path_exists") is False:
        return ORPHANED
    if values.get("volume_exists") is False:
        return MISSING_VOLUME
    if values.get("path_exists") is False:
        return STALE
    if values.get("path_exists") is True:
        return ACTIVE
    return UNKNOWN
