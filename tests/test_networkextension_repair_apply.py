from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.networkextension_manual_repair_runbook import build_networkextension_manual_repair_runbook
from macos_state_explorer.networkextension_repair_artifact import build_networkextension_repair_artifact
from macos_state_explorer.networkextension_repair_apply import apply_networkextension_repair_artifact
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview
from macos_state_explorer.networkextension_repair_simulation import build_networkextension_repair_simulation
from macos_state_explorer.networkextension_repair_transaction_package import build_networkextension_repair_transaction_package
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle

CONFIRM = "APPLY_NETWORKEXTENSION_REPAIR_ARTIFACT"


def write_candidate_fixture(root: Path) -> dict[str, Path]:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    installed_exe = root / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    missing_clone = root / "private" / "var" / "folders" / "xx" / "com.google.Chrome.code_sign_clone" / "Contents" / "MacOS" / "Google Chrome"
    missing_normal = root / "Applications" / "Missing Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    objects = [
        "$null",
        {"ClientIdentities": plistlib.UID(2)},
        [plistlib.UID(3), plistlib.UID(5), plistlib.UID(7), plistlib.UID(9)],
        {"ClientIdentity": plistlib.UID(4), "State": "active"},
        {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_exe)},
        {"ClientIdentity": plistlib.UID(6), "State": "historical"},
        {"SigningIdentifier": "com.google.Chrome.code_sign_clone", "Path": str(missing_clone)},
        {"ClientIdentity": plistlib.UID(8), "State": "orphaned"},
        {"SigningIdentifier": "com.google.Chrome", "Path": str(missing_normal)},
    ]
    artifact = prefs / "com.apple.networkextension.plist"
    with artifact.open("wb") as handle:
        plistlib.dump({"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": plistlib.UID(1)}, "$objects": objects}, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    return {"root": root, "artifact": artifact}


def generated_artifact(tmp_path: Path) -> dict[str, Path]:
    fixture = write_candidate_fixture(tmp_path / "ne")
    validation = build_networkextension_candidate_validation([fixture["root"]], process_rows=[])
    preview = build_networkextension_repair_plan_preview(validation)
    package = build_networkextension_repair_transaction_package(preview, [fixture["root"]])
    runbook = build_networkextension_manual_repair_runbook(package, [fixture["root"]])
    simulation = build_networkextension_repair_simulation(runbook, [fixture["root"]])
    output = tmp_path / "generated" / "networkextension-repair-artifact.plist"
    artifact = build_networkextension_repair_artifact(runbook, simulation, output, [fixture["root"]])
    metadata = tmp_path / "generated" / "networkextension-repair-artifact.json"
    metadata.write_text(json.dumps(artifact.to_json_dict(), sort_keys=True), encoding="utf-8")
    return {"root": fixture["root"], "source": fixture["artifact"], "artifact": output, "metadata": metadata}


def test_apply_repair_artifact_dry_run_is_non_mutating_and_deterministic(tmp_path):
    fixture = generated_artifact(tmp_path)
    before = fixture["source"].read_bytes()

    first = apply_networkextension_repair_artifact(fixture["artifact"], fixture["metadata"], target_path=fixture["source"], backup_dir=tmp_path / "backups", process_names=[], confirm_apply=None, protected_target=fixture["source"]).to_json_dict()
    second = apply_networkextension_repair_artifact(fixture["artifact"], fixture["metadata"], target_path=fixture["source"], backup_dir=tmp_path / "backups", process_names=[], confirm_apply=None, protected_target=fixture["source"]).to_json_dict()

    assert first == second
    assert first["command"] == "networkextension apply-repair-artifact"
    assert first["dry_run"] is True
    assert first["mutation_performed"] is False
    assert first["backup_created"] is False
    assert first["final_status"] == "DRY_RUN"
    assert "missing_explicit_confirmation" in first["blockers"]
    assert fixture["source"].read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_apply_repair_artifact_blocks_hash_path_confirmation_and_malformed_inputs(tmp_path):
    fixture = generated_artifact(tmp_path)
    bad_metadata = json.loads(fixture["metadata"].read_text())
    bad_metadata["source_sha256"] = "0" * 64
    mismatch_metadata = tmp_path / "mismatch.json"
    mismatch_metadata.write_text(json.dumps(bad_metadata), encoding="utf-8")
    mismatch = apply_networkextension_repair_artifact(fixture["artifact"], mismatch_metadata, target_path=fixture["source"], backup_dir=tmp_path / "b1", process_names=[], confirm_apply=CONFIRM, protected_target=fixture["source"])
    assert mismatch.final_status == "BLOCKED"
    assert "source_sha256_mismatch" in mismatch.blockers

    unsafe = apply_networkextension_repair_artifact(fixture["artifact"], fixture["metadata"], target_path=tmp_path / "not-the-live-target.plist", backup_dir=tmp_path / "b2", process_names=[], confirm_apply=CONFIRM, protected_target=fixture["source"])
    assert unsafe.final_status == "BLOCKED"
    assert "target_path_not_exact_protected_networkextension_plist" in unsafe.blockers

    malformed = tmp_path / "malformed.plist"
    malformed.write_text("not a plist", encoding="utf-8")
    bad = apply_networkextension_repair_artifact(malformed, fixture["metadata"], target_path=fixture["source"], backup_dir=tmp_path / "b3", process_names=[], confirm_apply=CONFIRM, protected_target=fixture["source"])
    assert bad.final_status == "BLOCKED"
    assert "input_artifact_reparse_failed" in bad.blockers


def test_apply_repair_artifact_success_creates_backup_then_atomic_replace(tmp_path):
    fixture = generated_artifact(tmp_path)
    before_source_sha = json.loads(fixture["metadata"].read_text())["source_sha256"]

    result = apply_networkextension_repair_artifact(fixture["artifact"], fixture["metadata"], target_path=fixture["source"], backup_dir=tmp_path / "backups", process_names=[], confirm_apply=CONFIRM, protected_target=fixture["source"])
    payload = result.to_json_dict()

    assert payload["dry_run"] is False
    assert payload["mutation_performed"] is True
    assert payload["backup_created"] is True
    assert payload["final_status"] == "APPLIED"
    assert payload["source_sha256_before"] == before_source_sha
    assert payload["backup_sha256"] == before_source_sha
    assert payload["generated_artifact_sha256"] == json.loads(fixture["metadata"].read_text())["generated_artifact_sha256"]
    assert Path(payload["backup_path"]).exists()
    assert plistlib.load(fixture["source"].open("rb"))["$objects"]
    assert payload["rollback_commands"]
    assert payload["post_apply_validation_commands"]


def test_apply_repair_artifact_backup_hash_mismatch_blocks_write(monkeypatch, tmp_path):
    fixture = generated_artifact(tmp_path)
    import macos_state_explorer.networkextension_repair_apply as module
    real_sha = module._sha256_file
    calls = {"count": 0}

    def fake_sha(path: Path) -> str:
        calls["count"] += 1
        if path.name.startswith("com.apple.networkextension") and ".backup." in path.name:
            return "f" * 64
        return real_sha(path)

    monkeypatch.setattr(module, "_sha256_file", fake_sha)
    result = apply_networkextension_repair_artifact(fixture["artifact"], fixture["metadata"], target_path=fixture["source"], backup_dir=tmp_path / "backups", process_names=[], confirm_apply=CONFIRM, protected_target=fixture["source"])

    assert result.final_status == "BLOCKED"
    assert "backup_sha256_mismatch" in result.blockers
    assert result.mutation_performed is False


def test_apply_repair_artifact_cli_report_bundle_and_diff(monkeypatch, tmp_path):
    fixture = generated_artifact(tmp_path)
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    result = CliRunner().invoke(app, ["networkextension", "apply-repair-artifact", "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"]), "--target", str(fixture["source"]), "--backup-dir", str(tmp_path / "backups"), "--protected-target", str(fixture["source"]), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload)[:8] == ["command", "timestamp", "dry_run", "mutation_performed", "backup_created", "source_sha256_before", "backup_sha256", "generated_artifact_sha256"]
    assert payload["final_status"] == "DRY_RUN"
    text = CliRunner().invoke(app, ["networkextension", "apply-repair-artifact", "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"]), "--target", str(fixture["source"]), "--backup-dir", str(tmp_path / "backups"), "--protected-target", str(fixture["source"])]).stdout
    assert "NetworkExtension guarded repair artifact apply" in text
    assert "Dry run: true" in text
    assert "Mutation performed: false" in text

    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    report = build_local_network_report(Snapshot(host="h", created_at=1, observations=[Observation(collector="launchservices", started_at=1, ended_at=1, payload={"entries": []})]))
    summary = report.to_json_dict()["networkextension_repair_apply_summary"]
    assert summary["final_status"] in {"DRY_RUN", "BLOCKED"}
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-repair-apply.json").exists()
    assert (bundle / "networkextension-repair-apply.txt").exists()

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_repair_apply_summary": {"final_status": "DRY_RUN", "mutation_performed": False}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_repair_apply_summary": {"final_status": "APPLIED", "mutation_performed": True, "backup_created": True}}))
    diff = json.loads(CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"]).stdout)
    assert diff["networkextension_repair_apply_diff"]["status_before"] == "DRY_RUN"
    assert diff["networkextension_repair_apply_diff"]["status_after"] == "APPLIED"
    assert "NetworkExtension Repair Apply Diff" in CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
