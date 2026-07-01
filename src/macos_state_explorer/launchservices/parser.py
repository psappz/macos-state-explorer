from __future__ import annotations

from pathlib import Path

from macos_state_explorer.launchservices.classifier import classify_record
from macos_state_explorer.launchservices.models import LaunchServicesRecord

DEFAULT_TERMS = ["chrome", "google", "localnetwork", "bonjour", "edge", "safari", "firefox"]

KNOWN_FIELDS = {
    "bundle id": "bundle_id",
    "identifier": "identifier",
    "name": "name",
    "displayName": "display_name",
    "versionString": "version",
    "displayVersion": "display_version",
    "path": "path",
    "executable": "executable",
    "container": "container",
    "directory": "directory",
    "platform": "platform",
    "teamID": "team_id",
    "mount state": "mount_state",
    "bundle flags": "bundle_flags",
    "item flags": "item_flags",
    "activityTypes": "activity_types",
    "trustedCodeSignatures": "trusted_code_signatures",
    "reg date": "registration_date",
    "mod date": "modification_date",
    "rec mod date": "record_modification_date",
}

SEQUENCE_FIELDS = {"sequenceNumber", "sequence number", "sequence"}


def clean_path(value: str) -> str:
    path = _strip_trailing_hex(value)
    if path.startswith("~"):
        path = path.replace("~", str(Path.home()), 1)
    return path


def parse_lsdump(dump: str, terms: list[str] | None = None) -> list[LaunchServicesRecord]:
    records = []
    for block in iter_blocks(dump):
        if not _matches_terms(block, terms):
            continue
        records.append(parse_block(block))
    return records


def iter_blocks(dump: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    for line in dump.splitlines():
        if _is_separator(line):
            _append_block(blocks, current)
            current = []
            continue
        current.append(line)

    _append_block(blocks, current)
    return blocks


def parse_block(block: str) -> LaunchServicesRecord:
    values: dict[str, object] = {
        "raw_block": block,
        "node_not_found": "Bundle node not found on disk" in block,
    }
    unknown_fields: dict[str, str] = {}

    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in KNOWN_FIELDS:
            values[KNOWN_FIELDS[key]] = value
            continue
        if key in SEQUENCE_FIELDS:
            values["sequence_number"] = _parse_int(value)
            continue
        unknown_fields[key] = value

    path = values.get("path")
    if isinstance(path, str):
        path_clean = clean_path(path)
        values["path_clean"] = path_clean
        values["path_exists"] = Path(path_clean).exists()
        volume = _volume_for_path(path_clean)
        values["volume"] = volume
        values["volume_exists"] = Path(volume).exists() if volume else None

    values["canonical_id"] = _canonical_id(values)
    values["fields"] = unknown_fields
    values["classification"] = classify_record(values)
    return LaunchServicesRecord(**values)


def _matches_terms(block: str, terms: list[str] | None) -> bool:
    if terms is None:
        return True
    if not terms:
        return True
    block_lower = block.lower()
    return any(term.lower() in block_lower for term in terms)


def _append_block(blocks: list[str], lines: list[str]) -> None:
    block = "\n".join(lines).strip()
    if block:
        blocks.append(block)


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 20 and set(stripped) == {"-"}


def _strip_trailing_hex(value: str) -> str:
    value = value.strip()
    marker = " (0x"
    if marker in value and value.endswith(")"):
        return value.rsplit(marker, 1)[0].strip()
    return value


def _parse_int(value: str) -> int | None:
    raw_value = value.strip()
    try:
        return int(raw_value, 0)
    except ValueError:
        return None


def _canonical_id(values: dict[str, object]) -> str | None:
    identifier = values.get("identifier")
    if isinstance(identifier, str) and identifier:
        return identifier
    bundle_id = values.get("bundle_id")
    if isinstance(bundle_id, str) and bundle_id:
        return _strip_trailing_hex(bundle_id)
    return None


def _volume_for_path(path: str) -> str | None:
    if path.startswith("/Volumes/"):
        parts = Path(path).parts
        if len(parts) >= 3:
            return "/" + "/".join(parts[1:3])
        return "/Volumes"
    if path.startswith("/"):
        return "/"
    return None
