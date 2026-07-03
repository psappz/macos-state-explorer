from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

CONFIRMATION_STRING = "APPLY_NETWORKEXTENSION_REPAIR_ARTIFACT"
DEFAULT_TARGET = Path("/Library/Preferences/com.apple.networkextension.plist")
DEFAULT_BACKUP_DIR = Path("networkextension-repair-backups")
DEFAULT_ARTIFACT = Path("networkextension-repair-artifact.plist")
DEFAULT_METADATA = Path("networkextension-repair-artifact.json")
REQUIRED_METADATA_FIELDS = (
    "command",
    "generated_artifact_sha256",
    "output_path",
    "reparse.success",
    "source_artifact.path",
    "source_sha256",
    "validation_result",
)


@dataclass(frozen=True)
class NetworkExtensionRepairApplyResult:
    dry_run: bool
    mutation_performed: bool
    backup_created: bool
    source_sha256_before: str
    backup_sha256: str
    generated_artifact_sha256: str
    target_path: Path
    backup_path: Path | None
    timestamp: str
    preflight_checks: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    post_apply_validation_commands: tuple[str, ...]
    rollback_commands: tuple[str, ...]
    final_status: str
    blocker_details: dict[str, dict[str, Any]]
    expected_source_sha256: str
    actual_source_sha256: str
    artifact_path: Path
    metadata_path: Path
    metadata_status: str
    preflight_status: str
    can_apply_with_confirmation: bool

    def summary(self) -> dict[str, Any]:
        return {
            "final_status": self.final_status,
            "dry_run": self.dry_run,
            "mutation_performed": self.mutation_performed,
            "backup_created": self.backup_created,
            "blockers": list(self.blockers),
            "blocker_details": self.blocker_details,
            "expected_source_sha256": self.expected_source_sha256,
            "actual_source_sha256": self.actual_source_sha256,
            "source_sha256_before": self.source_sha256_before,
            "backup_sha256": self.backup_sha256,
            "generated_artifact_sha256": self.generated_artifact_sha256,
            "artifact_path": str(self.artifact_path),
            "target_path": str(self.target_path),
            "backup_path": str(self.backup_path) if self.backup_path else "",
            "metadata_status": self.metadata_status,
            "preflight_status": self.preflight_status,
            "can_apply_with_confirmation": self.can_apply_with_confirmation,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension apply-repair-artifact",
            "timestamp": self.timestamp,
            "final_status": self.final_status,
            "dry_run": self.dry_run,
            "mutation_performed": self.mutation_performed,
            "backup_created": self.backup_created,
            "blockers": list(self.blockers),
            "blocker_details": self.blocker_details,
            "expected_source_sha256": self.expected_source_sha256,
            "actual_source_sha256": self.actual_source_sha256,
            "source_sha256_before": self.source_sha256_before,
            "backup_sha256": self.backup_sha256,
            "generated_artifact_sha256": self.generated_artifact_sha256,
            "artifact_path": str(self.artifact_path),
            "target_path": str(self.target_path),
            "backup_path": str(self.backup_path) if self.backup_path else "",
            "metadata_status": self.metadata_status,
            "preflight_status": self.preflight_status,
            "can_apply_with_confirmation": self.can_apply_with_confirmation,
            "metadata_path": str(self.metadata_path),
            "preflight_checks": list(self.preflight_checks),
            "post_apply_validation_commands": list(self.post_apply_validation_commands),
            "rollback_commands": list(self.rollback_commands),
        }


def apply_networkextension_repair_artifact(
    artifact_path: Path = DEFAULT_ARTIFACT,
    metadata_path: Path = DEFAULT_METADATA,
    *,
    target_path: Path = DEFAULT_TARGET,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    process_names: Sequence[str] | None = None,
    confirm_apply: str | None = None,
    protected_target: Path = DEFAULT_TARGET,
    timestamp: str = "1970-01-01T00:00:00Z",
) -> NetworkExtensionRepairApplyResult:
    artifact = Path(artifact_path).expanduser()
    metadata_file = Path(metadata_path).expanduser()
    target = Path(target_path).expanduser()
    backup_root = Path(backup_dir).expanduser()
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    details: dict[str, dict[str, Any]] = {}
    source_sha = ""
    backup_sha = ""
    generated_sha = ""
    expected_source = ""
    backup_path: Path | None = None

    metadata, metadata_status = _load_metadata(metadata_file, checks, blockers, details)
    expected_source = str(metadata.get("source_sha256", "")) if isinstance(metadata, dict) else ""
    artifact_bytes = _read_reparsable_artifact(artifact, checks, blockers, details)
    if artifact_bytes is not None:
        generated_sha = hashlib.sha256(artifact_bytes).hexdigest()
    expected_generated = str(metadata.get("generated_artifact_sha256", "")) if isinstance(metadata, dict) else ""
    if expected_generated and generated_sha and expected_generated != generated_sha:
        blockers.append("generated_artifact_sha256_mismatch")
        checks.append(_check("generated_artifact_sha256_matches_metadata", False))
        details["generated_artifact_sha256_mismatch"] = {
            "explanation": "The generated artifact bytes do not match the sidecar metadata SHA256.",
            "expected_generated_artifact_sha256": expected_generated,
            "actual_generated_artifact_sha256": generated_sha,
            "artifact_path": str(artifact),
            "metadata_path": str(metadata_file),
        }
    else:
        checks.append(_check("generated_artifact_sha256_matches_metadata", bool(generated_sha)))

    source_exists = target.is_file()
    checks.append(_check("source_system_artifact_exists", source_exists, str(target)))
    if not source_exists:
        blockers.append("source_system_artifact_missing")
        details["source_system_artifact_missing"] = {
            "explanation": "The protected source NetworkExtension plist does not exist at the target path.",
            "target_path": str(target),
        }
    else:
        source_sha = _sha256_file(target)
        if not expected_source or source_sha != expected_source:
            blockers.append("source_sha256_mismatch")
            checks.append(_check("source_sha256_matches_metadata", False))
            details["source_sha256_mismatch"] = {
                "explanation": "The generated artifact metadata does not match the current protected source plist. Do not apply until a fresh artifact is generated from the current source.",
                "expected_source_sha256": expected_source,
                "actual_source_sha256": source_sha,
                "target_path": str(target),
                "artifact_path": str(artifact),
                "metadata_path": str(metadata_file),
                "artifact_source_relationship": _artifact_source_relationship(metadata, target, expected_source, source_sha),
            }
        else:
            checks.append(_check("source_sha256_matches_metadata", True))

    target_ok = target.resolve(strict=False) == Path(protected_target).expanduser().resolve(strict=False)
    checks.append(_check("target_is_exact_protected_networkextension_plist", target_ok, str(target)))
    if not target_ok:
        blockers.append("target_path_not_exact_protected_networkextension_plist")
        details["target_path_not_exact_protected_networkextension_plist"] = {
            "explanation": "The apply command is restricted to the exact protected NetworkExtension plist target; alternate paths are blocked.",
            "target_path": str(target),
            "protected_target": str(Path(protected_target).expanduser()),
        }

    backup_safe = _is_user_controlled_backup_dir(backup_root, target)
    checks.append(_check("backup_destination_user_controlled", backup_safe, str(backup_root)))
    if not backup_safe:
        blockers.append("backup_destination_not_user_controlled")
        details["backup_destination_not_user_controlled"] = {
            "explanation": "Backup destination must be user-controlled and outside protected/system locations.",
            "backup_dir": str(backup_root),
        }

    names = tuple(process_names) if process_names is not None else _current_process_names()
    system_settings_closed = not any(name in {"System Settings", "System Preferences"} for name in names)
    chrome_closed = not any("Chrome" in name for name in names)
    checks.append(_check("system_settings_closed", system_settings_closed))
    checks.append(_check("chrome_not_running", chrome_closed))
    if not system_settings_closed:
        blockers.append("system_settings_running")
        details["system_settings_running"] = {
            "explanation": "Close System Settings before applying because it can read/write or cache the same NetworkExtension preference state.",
            "running_processes": [name for name in names if name in {"System Settings", "System Preferences"}],
        }
    if not chrome_closed:
        blockers.append("chrome_running")
        details["chrome_running"] = {
            "explanation": "Close Chrome before applying so no Chrome process is actively interacting with Local Network or NetworkExtension state.",
            "running_processes": [name for name in names if "Chrome" in name],
        }

    confirmed = confirm_apply == CONFIRMATION_STRING
    checks.append(_check("explicit_confirmation_string", confirmed))
    if not confirmed:
        blockers.append("missing_explicit_confirmation")
        details["missing_explicit_confirmation"] = {
            "explanation": "A real apply requires the exact confirmation flag; dry-run/preflight never writes without it.",
            "required_confirmation_flag": f"--confirm-apply {CONFIRMATION_STRING}",
        }

    unique_blockers = tuple(dict.fromkeys(blockers))
    validation_commands = _validation_commands(target)
    rollback = _rollback_commands(target, backup_path)
    preflight_status = _preflight_status(unique_blockers, confirmed, applied=False)
    can_apply = unique_blockers == ("missing_explicit_confirmation",)
    if unique_blockers or not confirmed:
        status = "DRY_RUN" if not confirmed else "BLOCKED"
        return NetworkExtensionRepairApplyResult(
            dry_run=True,
            mutation_performed=False,
            backup_created=False,
            source_sha256_before=source_sha,
            backup_sha256="",
            generated_artifact_sha256=generated_sha,
            target_path=target,
            backup_path=None,
            timestamp=timestamp,
            preflight_checks=tuple(checks),
            blockers=unique_blockers,
            post_apply_validation_commands=validation_commands,
            rollback_commands=rollback,
            final_status=status,
            blocker_details={code: details.get(code, _generic_blocker_detail(code)) for code in unique_blockers},
            expected_source_sha256=expected_source,
            actual_source_sha256=source_sha,
            artifact_path=artifact,
            metadata_path=metadata_file,
            metadata_status=metadata_status,
            preflight_status=preflight_status,
            can_apply_with_confirmation=can_apply,
        )

    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"{target.name}.backup.{_backup_stamp(timestamp)}"
    shutil.copy2(target, backup_path)
    backup_sha = _sha256_file(backup_path)
    if backup_sha != source_sha:
        blockers.append("backup_sha256_mismatch")
        unique_blockers = tuple(dict.fromkeys(blockers))
        checks.append(_check("backup_sha256_equals_source_sha256", False))
        details["backup_sha256_mismatch"] = {
            "explanation": "Backup SHA256 must match the source SHA256 before any write is attempted.",
            "source_sha256": source_sha,
            "backup_sha256": backup_sha,
            "backup_path": str(backup_path),
        }
        return NetworkExtensionRepairApplyResult(
            dry_run=False,
            mutation_performed=False,
            backup_created=True,
            source_sha256_before=source_sha,
            backup_sha256=backup_sha,
            generated_artifact_sha256=generated_sha,
            target_path=target,
            backup_path=backup_path,
            timestamp=timestamp,
            preflight_checks=tuple(checks),
            blockers=unique_blockers,
            post_apply_validation_commands=validation_commands,
            rollback_commands=_rollback_commands(target, backup_path),
            final_status="BLOCKED",
            blocker_details={code: details.get(code, _generic_blocker_detail(code)) for code in unique_blockers},
            expected_source_sha256=expected_source,
            actual_source_sha256=source_sha,
            artifact_path=artifact,
            metadata_path=metadata_file,
            metadata_status=metadata_status,
            preflight_status="BLOCKED",
            can_apply_with_confirmation=False,
        )
    checks.append(_check("backup_sha256_equals_source_sha256", True))

    _atomic_write(target, artifact_bytes or b"")
    return NetworkExtensionRepairApplyResult(
        dry_run=False,
        mutation_performed=True,
        backup_created=True,
        source_sha256_before=source_sha,
        backup_sha256=backup_sha,
        generated_artifact_sha256=generated_sha,
        target_path=target,
        backup_path=backup_path,
        timestamp=timestamp,
        preflight_checks=tuple(checks),
        blockers=(),
        post_apply_validation_commands=validation_commands,
        rollback_commands=_rollback_commands(target, backup_path),
        final_status="APPLIED",
        blocker_details={},
        expected_source_sha256=expected_source,
        actual_source_sha256=source_sha,
        artifact_path=artifact,
        metadata_path=metadata_file,
        metadata_status=metadata_status,
        preflight_status="APPLIED",
        can_apply_with_confirmation=False,
    )


def networkextension_repair_apply_summary(result: NetworkExtensionRepairApplyResult) -> dict[str, Any]:
    return result.summary()


def render_networkextension_repair_apply(result: NetworkExtensionRepairApplyResult) -> str:
    lines = [
        "NetworkExtension guarded repair artifact apply",
        f"- Final status: {result.final_status}",
        f"- Dry run: {str(result.dry_run).lower()}",
        f"- Mutation performed: {str(result.mutation_performed).lower()}",
        f"- Backup created: {str(result.backup_created).lower()}",
        f"- Metadata status: {result.metadata_status}",
        f"- Preflight status: {result.preflight_status}",
        f"- Can apply with confirmation: {str(result.can_apply_with_confirmation).lower()}",
        f"- Artifact path: {result.artifact_path}",
        f"- Target path: {result.target_path}",
        f"- Backup path: {result.backup_path or ''}",
        f"- Expected source SHA256: {result.expected_source_sha256}",
        f"- Actual source SHA256: {result.actual_source_sha256}",
        f"- Generated artifact SHA256: {result.generated_artifact_sha256}",
        f"- Blockers: {', '.join(result.blockers) if result.blockers else 'none'}",
    ]
    if result.blocker_details:
        lines.append("- Blocker details:")
        for code in result.blockers:
            detail = result.blocker_details.get(code, {})
            lines.append(f"  - {code}: {detail.get('explanation', '')}")
            if code == "missing_explicit_confirmation":
                lines.append(f"    Required: {detail.get('required_confirmation_flag', '')}")
            if code == "source_sha256_mismatch":
                lines.append(f"    Expected: {detail.get('expected_source_sha256', '')}")
                lines.append(f"    Actual: {detail.get('actual_source_sha256', '')}")
                lines.append(f"    Relationship: {detail.get('artifact_source_relationship', '')}")
    lines.extend([
        "- This command never deletes files, edits LaunchServices, resets TCC, or modifies anything except the single confirmed target plist.",
        "- Rollback commands:",
        *[f"  - {command}" for command in result.rollback_commands],
        "- Post-apply validation commands:",
        *[f"  - {command}" for command in result.post_apply_validation_commands],
    ])
    return "\n".join(lines)


def render_networkextension_repair_apply_summary(summary: dict[str, Any]) -> str:
    lines = [
        "NetworkExtension guarded repair artifact apply",
        f"- Final status: {summary.get('final_status', 'DRY_RUN')}",
        f"- Dry run: {str(summary.get('dry_run', True)).lower()}",
        f"- Mutation performed: {str(summary.get('mutation_performed', False)).lower()}",
        f"- Backup created: {str(summary.get('backup_created', False)).lower()}",
        f"- Metadata status: {summary.get('metadata_status', 'UNKNOWN')}",
        f"- Preflight status: {summary.get('preflight_status', 'BLOCKED')}",
        f"- Can apply with confirmation: {str(summary.get('can_apply_with_confirmation', False)).lower()}",
        f"- Target path: {summary.get('target_path', '')}",
    ]
    blockers = summary.get("blockers", [])
    if blockers:
        lines.append(f"- Blockers: {', '.join(str(b) for b in blockers)}")
    return "\n".join(lines)


def _load_metadata(
    path: Path,
    checks: list[dict[str, Any]],
    blockers: list[str],
    details: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        blockers.append("metadata_missing")
        checks.append(_check("metadata_exists", False, str(path)))
        details["metadata_missing"] = {
            "explanation": "The apply command requires deterministic sidecar JSON metadata generated alongside the repair artifact.",
            "metadata_path": str(path),
            "missing_files": [str(path)],
            "missing_fields": list(REQUIRED_METADATA_FIELDS),
            "expected_metadata_format": "sidecar_json",
        }
        return {}, "MISSING"
    checks.append(_check("metadata_exists", True, str(path)))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        blockers.append("metadata_parse_failed")
        checks.append(_check("metadata_parses", False, str(path)))
        details["metadata_parse_failed"] = {
            "explanation": "The metadata sidecar exists but is not parseable JSON.",
            "metadata_path": str(path),
            "error": type(error).__name__,
            "expected_metadata_format": "sidecar_json",
        }
        return {}, "PARSE_FAILED"
    is_dict = isinstance(value, dict)
    checks.append(_check("metadata_parses", is_dict, str(path)))
    if not is_dict:
        blockers.append("metadata_parse_failed")
        details["metadata_parse_failed"] = {
            "explanation": "The metadata sidecar must contain a JSON object.",
            "metadata_path": str(path),
            "expected_metadata_format": "sidecar_json",
        }
        return {}, "PARSE_FAILED"
    missing_fields = _missing_metadata_fields(value)
    if missing_fields:
        blockers.append("metadata_missing")
        checks.append(_check("metadata_required_fields_present", False, ", ".join(missing_fields)))
        details["metadata_missing"] = {
            "explanation": "The metadata sidecar is present but required fields are missing; do not infer missing metadata from assumptions.",
            "metadata_path": str(path),
            "missing_files": [],
            "missing_fields": missing_fields,
            "expected_metadata_format": "sidecar_json",
        }
        return value, "INCOMPLETE"
    checks.append(_check("metadata_required_fields_present", True, str(path)))
    return value, "VALID"


def _missing_metadata_fields(metadata: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_METADATA_FIELDS:
        value: Any = metadata
        for part in field.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                missing.append(field)
                break
        else:
            if value in (None, ""):
                missing.append(field)
    return missing


def _read_reparsable_artifact(
    path: Path,
    checks: list[dict[str, Any]],
    blockers: list[str],
    details: dict[str, dict[str, Any]],
) -> bytes | None:
    if not path.is_file():
        blockers.append("input_artifact_missing")
        checks.append(_check("input_artifact_exists", False, str(path)))
        details["input_artifact_missing"] = {"explanation": "The generated repair artifact plist does not exist.", "artifact_path": str(path)}
        return None
    checks.append(_check("input_artifact_exists", True, str(path)))
    data = path.read_bytes()
    try:
        plistlib.loads(data)
    except Exception as error:
        blockers.append("input_artifact_reparse_failed")
        checks.append(_check("input_artifact_reparses", False, str(path)))
        details["input_artifact_reparse_failed"] = {
            "explanation": "The generated repair artifact must reparse as a plist before any apply is considered.",
            "artifact_path": str(path),
            "error": type(error).__name__,
        }
        return data
    checks.append(_check("input_artifact_reparses", True, str(path)))
    return data


def _artifact_source_relationship(metadata: dict[str, Any], target: Path, expected_source: str, actual_source: str) -> str:
    source_artifact = metadata.get("source_artifact") if isinstance(metadata, dict) else None
    source_path = source_artifact.get("path") if isinstance(source_artifact, dict) else ""
    if source_path and Path(source_path).expanduser().resolve(strict=False) != target.resolve(strict=False):
        return "different_source_path"
    if expected_source and actual_source and expected_source != actual_source:
        return "same_source_path_but_hash_changed"
    if not expected_source:
        return "missing_source_metadata"
    return "undetermined"


def _preflight_status(blockers: tuple[str, ...], confirmed: bool, *, applied: bool) -> str:
    if applied:
        return "APPLIED"
    if blockers == ("missing_explicit_confirmation",):
        return "READY_WITH_CONFIRMATION"
    if blockers:
        return "BLOCKED"
    return "READY" if not confirmed else "READY_TO_APPLY"


def _generic_blocker_detail(code: str) -> dict[str, Any]:
    return {"explanation": f"Apply preflight blocker: {code}"}


def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def _is_user_controlled_backup_dir(path: Path, target: Path) -> bool:
    resolved = path.resolve(strict=False)
    if resolved == target.resolve(strict=False) or resolved in target.resolve(strict=False).parents:
        return False
    protected_prefixes = (Path("/Library"), Path("/System"), Path("/private/var/db"), Path("/Library/Preferences"))
    for prefix in protected_prefixes:
        try:
            resolved.relative_to(prefix)
            return False
        except ValueError:
            continue
    return True


def _current_process_names() -> tuple[str, ...]:
    try:
        output = subprocess.check_output(["ps", "-axo", "comm="], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ()
    return tuple(Path(line.strip()).name for line in output.splitlines() if line.strip())


def _validation_commands(target: Path) -> tuple[str, ...]:
    return (
        f"plutil -lint {target}",
        "mse networkextension validate-candidates",
        "mse networkextension repair-simulation",
        "mse report local-network --bundle post-apply-networkextension-bundle",
    )


def _rollback_commands(target: Path, backup_path: Path | None) -> tuple[str, ...]:
    if backup_path is None:
        return ("No backup created; no rollback command is available.",)
    return (f"cp {backup_path} {target}", f"plutil -lint {target}")


def _backup_stamp(timestamp: str) -> str:
    if timestamp == "1970-01-01T00:00:00Z":
        return "19700101T000000Z"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def _atomic_write(target: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
