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

    def summary(self) -> dict[str, Any]:
        return {
            "final_status": self.final_status,
            "dry_run": self.dry_run,
            "mutation_performed": self.mutation_performed,
            "backup_created": self.backup_created,
            "source_sha256_before": self.source_sha256_before,
            "backup_sha256": self.backup_sha256,
            "generated_artifact_sha256": self.generated_artifact_sha256,
            "target_path": str(self.target_path),
            "backup_path": str(self.backup_path) if self.backup_path else "",
            "blockers": list(self.blockers),
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "networkextension apply-repair-artifact",
            "timestamp": self.timestamp,
            "dry_run": self.dry_run,
            "mutation_performed": self.mutation_performed,
            "backup_created": self.backup_created,
            "source_sha256_before": self.source_sha256_before,
            "backup_sha256": self.backup_sha256,
            "generated_artifact_sha256": self.generated_artifact_sha256,
            "target_path": str(self.target_path),
            "backup_path": str(self.backup_path) if self.backup_path else "",
            "preflight_checks": list(self.preflight_checks),
            "blockers": list(self.blockers),
            "post_apply_validation_commands": list(self.post_apply_validation_commands),
            "rollback_commands": list(self.rollback_commands),
            "final_status": self.final_status,
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
    source_sha = ""
    backup_sha = ""
    generated_sha = ""
    backup_path: Path | None = None

    metadata = _load_metadata(metadata_file, checks, blockers)
    artifact_bytes = _read_reparsable_artifact(artifact, checks, blockers)
    if artifact_bytes is not None:
        generated_sha = hashlib.sha256(artifact_bytes).hexdigest()
    expected_generated = str(metadata.get("generated_artifact_sha256", "")) if isinstance(metadata, dict) else ""
    if expected_generated and generated_sha and expected_generated != generated_sha:
        blockers.append("generated_artifact_sha256_mismatch")
        checks.append(_check("generated_artifact_sha256_matches_metadata", False))
    else:
        checks.append(_check("generated_artifact_sha256_matches_metadata", bool(generated_sha)))

    source_exists = target.is_file()
    checks.append(_check("source_system_artifact_exists", source_exists, str(target)))
    if not source_exists:
        blockers.append("source_system_artifact_missing")
    else:
        source_sha = _sha256_file(target)
        expected_source = str(metadata.get("source_sha256", "")) if isinstance(metadata, dict) else ""
        if not expected_source or source_sha != expected_source:
            blockers.append("source_sha256_mismatch")
            checks.append(_check("source_sha256_matches_metadata", False))
        else:
            checks.append(_check("source_sha256_matches_metadata", True))

    target_ok = target.resolve(strict=False) == Path(protected_target).expanduser().resolve(strict=False)
    checks.append(_check("target_is_exact_protected_networkextension_plist", target_ok, str(target)))
    if not target_ok:
        blockers.append("target_path_not_exact_protected_networkextension_plist")

    backup_safe = _is_user_controlled_backup_dir(backup_root, target)
    checks.append(_check("backup_destination_user_controlled", backup_safe, str(backup_root)))
    if not backup_safe:
        blockers.append("backup_destination_not_user_controlled")

    names = tuple(process_names) if process_names is not None else _current_process_names()
    system_settings_closed = not any(name in {"System Settings", "System Preferences"} for name in names)
    chrome_closed = not any("Chrome" in name for name in names)
    checks.append(_check("system_settings_closed", system_settings_closed))
    checks.append(_check("chrome_not_running", chrome_closed))
    if not system_settings_closed:
        blockers.append("system_settings_running")
    if not chrome_closed:
        blockers.append("chrome_running")

    confirmed = confirm_apply == CONFIRMATION_STRING
    checks.append(_check("explicit_confirmation_string", confirmed))
    if not confirmed:
        blockers.append("missing_explicit_confirmation")

    validation_commands = _validation_commands(target)
    rollback = _rollback_commands(target, backup_path)
    if blockers or not confirmed:
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
            blockers=tuple(dict.fromkeys(blockers)),
            post_apply_validation_commands=validation_commands,
            rollback_commands=rollback,
            final_status=status,
        )

    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"{target.name}.backup.{_backup_stamp(timestamp)}"
    shutil.copy2(target, backup_path)
    backup_sha = _sha256_file(backup_path)
    if backup_sha != source_sha:
        blockers.append("backup_sha256_mismatch")
        checks.append(_check("backup_sha256_equals_source_sha256", False))
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
            blockers=tuple(dict.fromkeys(blockers)),
            post_apply_validation_commands=validation_commands,
            rollback_commands=_rollback_commands(target, backup_path),
            final_status="BLOCKED",
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
    )


def networkextension_repair_apply_summary(result: NetworkExtensionRepairApplyResult) -> dict[str, Any]:
    return result.summary()


def render_networkextension_repair_apply(result: NetworkExtensionRepairApplyResult) -> str:
    return "\n".join([
        "NetworkExtension guarded repair artifact apply",
        f"- Dry run: {str(result.dry_run).lower()}",
        f"- Mutation performed: {str(result.mutation_performed).lower()}",
        f"- Backup created: {str(result.backup_created).lower()}",
        f"- Final status: {result.final_status}",
        f"- Target path: {result.target_path}",
        f"- Backup path: {result.backup_path or ''}",
        f"- Source SHA256 before: {result.source_sha256_before}",
        f"- Backup SHA256: {result.backup_sha256}",
        f"- Generated artifact SHA256: {result.generated_artifact_sha256}",
        f"- Blockers: {', '.join(result.blockers) if result.blockers else 'none'}",
        "- This command never deletes files, edits LaunchServices, resets TCC, or modifies anything except the single confirmed target plist.",
        "- Rollback commands:",
        *[f"  - {command}" for command in result.rollback_commands],
        "- Post-apply validation commands:",
        *[f"  - {command}" for command in result.post_apply_validation_commands],
    ])


def render_networkextension_repair_apply_summary(summary: dict[str, Any]) -> str:
    return "\n".join([
        "NetworkExtension guarded repair artifact apply",
        f"- Final status: {summary.get('final_status', 'DRY_RUN')}",
        f"- Dry run: {str(summary.get('dry_run', True)).lower()}",
        f"- Mutation performed: {str(summary.get('mutation_performed', False)).lower()}",
        f"- Backup created: {str(summary.get('backup_created', False)).lower()}",
        f"- Target path: {summary.get('target_path', '')}",
    ])


def _load_metadata(path: Path, checks: list[dict[str, Any]], blockers: list[str]) -> dict[str, Any]:
    if not path.is_file():
        blockers.append("metadata_missing")
        checks.append(_check("metadata_exists", False, str(path)))
        return {}
    checks.append(_check("metadata_exists", True, str(path)))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        blockers.append("metadata_parse_failed")
        checks.append(_check("metadata_parses", False, str(path)))
        return {}
    checks.append(_check("metadata_parses", isinstance(value, dict), str(path)))
    return value if isinstance(value, dict) else {}


def _read_reparsable_artifact(path: Path, checks: list[dict[str, Any]], blockers: list[str]) -> bytes | None:
    if not path.is_file():
        blockers.append("input_artifact_missing")
        checks.append(_check("input_artifact_exists", False, str(path)))
        return None
    checks.append(_check("input_artifact_exists", True, str(path)))
    data = path.read_bytes()
    try:
        plistlib.loads(data)
    except Exception:
        blockers.append("input_artifact_reparse_failed")
        checks.append(_check("input_artifact_reparses", False, str(path)))
        return data
    checks.append(_check("input_artifact_reparses", True, str(path)))
    return data


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
