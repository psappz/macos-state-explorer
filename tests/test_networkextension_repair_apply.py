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
    assert first["metadata_status"] == "VALID"
    assert first["preflight_status"] == "READY_WITH_CONFIRMATION"
    assert first["can_apply_with_confirmation"] is True
    assert first["expected_source_sha256"] == json.loads(fixture["metadata"].read_text())["source_sha256"]
    assert first["actual_source_sha256"] == first["source_sha256_before"]
    assert first["artifact_path"] == str(fixture["artifact"])
    confirmation_detail = first["blocker_details"]["missing_explicit_confirmation"]
    assert confirmation_detail["required_confirmation_flag"] == "--confirm-apply APPLY_NETWORKEXTENSION_REPAIR_ARTIFACT"
    assert "exact confirmation flag" in confirmation_detail["explanation"]
    assert fixture["source"].read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_apply_repair_artifact_blocks_hash_path_confirmation_and_malformed_inputs(tmp_path):
    fixture = generated_artifact(tmp_path)
    bad_metadata = json.loads(fixture["metadata"].read_text())
    bad_metadata["source_sha256"] = "0" * 64
    mismatch_metadata = tmp_path / "mismatch.json"
    mismatch_metadata.write_text(json.dumps(bad_metadata), encoding="utf-8")
    mismatch = apply_networkextension_repair_artifact(fixture["artifact"], mismatch_metadata, target_path=fixture["source"], backup_dir=tmp_path / "b1", process_names=[], confirm_apply=CONFIRM, protected_target=fixture["source"])
    mismatch_payload = mismatch.to_json_dict()
    assert mismatch.final_status == "BLOCKED"
    assert "source_sha256_mismatch" in mismatch.blockers
    assert mismatch_payload["expected_source_sha256"] == "0" * 64
    assert mismatch_payload["actual_source_sha256"] == mismatch_payload["source_sha256_before"]
    assert mismatch_payload["blocker_details"]["source_sha256_mismatch"]["target_path"] == str(fixture["source"])
    assert mismatch_payload["blocker_details"]["source_sha256_mismatch"]["artifact_path"] == str(fixture["artifact"])
    assert mismatch_payload["blocker_details"]["source_sha256_mismatch"]["artifact_source_relationship"] == "same_source_path_but_hash_changed"

    unsafe = apply_networkextension_repair_artifact(fixture["artifact"], fixture["metadata"], target_path=tmp_path / "not-the-live-target.plist", backup_dir=tmp_path / "b2", process_names=[], confirm_apply=CONFIRM, protected_target=fixture["source"])
    assert unsafe.final_status == "BLOCKED"
    assert "target_path_not_exact_protected_networkextension_plist" in unsafe.blockers
    assert unsafe.to_json_dict()["blocker_details"]["target_path_not_exact_protected_networkextension_plist"]["protected_target"] == str(fixture["source"])

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
    assert payload["preflight_status"] == "APPLIED"
    assert payload["can_apply_with_confirmation"] is False
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


def test_apply_repair_artifact_reports_missing_metadata_fields_exactly(tmp_path):
    fixture = generated_artifact(tmp_path)
    partial_metadata = tmp_path / "partial.json"
    partial_metadata.write_text(
        json.dumps({"source_sha256": json.loads(fixture["metadata"].read_text())["source_sha256"]}),
        encoding="utf-8",
    )

    payload = apply_networkextension_repair_artifact(
        fixture["artifact"],
        partial_metadata,
        target_path=fixture["source"],
        backup_dir=tmp_path / "backups",
        process_names=[],
        confirm_apply=CONFIRM,
        protected_target=fixture["source"],
    ).to_json_dict()

    assert payload["metadata_status"] == "INCOMPLETE"
    assert "metadata_missing" in payload["blockers"]
    assert payload["blocker_details"]["metadata_missing"]["metadata_path"] == str(partial_metadata)
    assert payload["blocker_details"]["metadata_missing"]["missing_fields"] == [
        "command",
        "generated_artifact_sha256",
        "output_path",
        "reparse.success",
        "source_artifact.path",
        "validation_result",
    ]


def test_apply_repair_artifact_reports_missing_metadata_file_exactly(tmp_path):
    fixture = generated_artifact(tmp_path)
    missing_metadata = tmp_path / "missing-sidecar.json"

    payload = apply_networkextension_repair_artifact(
        fixture["artifact"],
        missing_metadata,
        target_path=fixture["source"],
        backup_dir=tmp_path / "backups",
        process_names=[],
        confirm_apply=CONFIRM,
        protected_target=fixture["source"],
    ).to_json_dict()

    assert payload["metadata_status"] == "MISSING"
    assert "metadata_missing" in payload["blockers"]
    assert payload["blocker_details"]["metadata_missing"]["missing_files"] == [str(missing_metadata)]
    assert payload["blocker_details"]["metadata_missing"]["expected_metadata_format"] == "sidecar_json"


def test_apply_repair_artifact_explains_system_settings_running_blocker(tmp_path):
    fixture = generated_artifact(tmp_path)

    payload = apply_networkextension_repair_artifact(
        fixture["artifact"],
        fixture["metadata"],
        target_path=fixture["source"],
        backup_dir=tmp_path / "backups",
        process_names=["System Settings"],
        confirm_apply=CONFIRM,
        protected_target=fixture["source"],
    ).to_json_dict()

    assert payload["preflight_status"] == "BLOCKED"
    assert "system_settings_running" in payload["blockers"]
    assert "read/write or cache" in payload["blocker_details"]["system_settings_running"]["explanation"]


def test_apply_repair_artifact_cli_report_bundle_and_diff(monkeypatch, tmp_path):
    fixture = generated_artifact(tmp_path)
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    monkeypatch.setattr("macos_state_explorer.networkextension_repair_apply._current_process_names", lambda: ())
    result = CliRunner().invoke(app, ["networkextension", "apply-repair-artifact", "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"]), "--target", str(fixture["source"]), "--backup-dir", str(tmp_path / "backups"), "--protected-target", str(fixture["source"]), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload)[:18] == [
        "command",
        "timestamp",
        "final_status",
        "dry_run",
        "mutation_performed",
        "backup_created",
        "blockers",
        "blocker_details",
        "expected_source_sha256",
        "actual_source_sha256",
        "source_sha256_before",
        "backup_sha256",
        "generated_artifact_sha256",
        "artifact_path",
        "target_path",
        "backup_path",
        "metadata_status",
        "preflight_status",
    ]
    assert payload["final_status"] == "DRY_RUN"
    assert payload["can_apply_with_confirmation"] is True
    text = CliRunner().invoke(app, ["networkextension", "apply-repair-artifact", "--artifact", str(fixture["artifact"]), "--metadata", str(fixture["metadata"]), "--target", str(fixture["source"]), "--backup-dir", str(tmp_path / "backups"), "--protected-target", str(fixture["source"])]).stdout
    assert "NetworkExtension guarded repair artifact apply" in text
    assert "Dry run: true" in text
    assert "Mutation performed: false" in text
    assert "Can apply with confirmation: true" in text
    assert "missing_explicit_confirmation" in text

    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    report = build_local_network_report(Snapshot(host="h", created_at=1, observations=[Observation(collector="launchservices", started_at=1, ended_at=1, payload={"entries": []})]))
    summary = report.to_json_dict()["networkextension_repair_apply_summary"]
    assert summary["final_status"] in {"DRY_RUN", "BLOCKED"}
    assert "blocker_details" in summary
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-repair-apply.json").exists()
    assert (bundle / "networkextension-repair-apply.txt").exists()

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_repair_apply_summary": {"final_status": "DRY_RUN", "mutation_performed": False, "blockers": ["missing_explicit_confirmation"], "blocker_details": {"missing_explicit_confirmation": {"explanation": "confirmation missing"}}}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_repair_apply_summary": {"final_status": "BLOCKED", "mutation_performed": False, "backup_created": False, "blockers": ["source_sha256_mismatch"], "blocker_details": {"source_sha256_mismatch": {"expected_source_sha256": "e", "actual_source_sha256": "a", "artifact_source_relationship": "same_source_path_but_hash_changed"}}, "expected_source_sha256": "e", "actual_source_sha256": "a"}}))
    diff = json.loads(CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"]).stdout)
    assert diff["networkextension_repair_apply_diff"]["status_before"] == "DRY_RUN"
    assert diff["networkextension_repair_apply_diff"]["status_after"] == "BLOCKED"
    assert diff["networkextension_repair_apply_diff"]["added_blockers"] == ["source_sha256_mismatch"]
    assert diff["networkextension_repair_apply_diff"]["removed_blockers"] == ["missing_explicit_confirmation"]
    assert diff["networkextension_repair_apply_diff"]["sha_mismatch_details_after"]["expected_source_sha256"] == "e"
    rendered_diff = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Repair Apply Diff" in rendered_diff
    assert "Added blockers: source_sha256_mismatch" in rendered_diff
