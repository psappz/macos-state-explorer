from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class LaunchServicesStatus(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    ORPHANED = "ORPHANED"
    MISSING_VOLUME = "MISSING_VOLUME"
    DUPLICATE = "DUPLICATE"
    SHADOWED = "SHADOWED"
    SUPERSEDED = "SUPERSEDED"
    BROKEN = "BROKEN"
    UNKNOWN = "UNKNOWN"


class LaunchServicesRecord(BaseModel):
    raw_block: str
    bundle_id: str | None = None
    identifier: str | None = None
    canonical_id: str | None = None
    sequence_number: int | None = None
    name: str | None = None
    display_name: str | None = None
    version: str | None = None
    display_version: str | None = None
    path: str | None = None
    path_clean: str | None = None
    path_exists: bool | None = None
    executable: str | None = None
    container: str | None = None
    directory: str | None = None
    volume: str | None = None
    volume_exists: bool | None = None
    platform: str | None = None
    team_id: str | None = None
    mount_state: str | None = None
    bundle_flags: str | None = None
    item_flags: str | None = None
    activity_types: str | None = None
    trusted_code_signatures: str | None = None
    registration_date: str | None = None
    modification_date: str | None = None
    record_modification_date: str | None = None
    node_not_found: bool = False
    classification: LaunchServicesStatus = LaunchServicesStatus.UNKNOWN
    fields: dict[str, str] = Field(default_factory=dict)
