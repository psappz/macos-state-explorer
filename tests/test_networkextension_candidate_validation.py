from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices(entries: list[dict] | None = None) -> Snapshot:
    return Snapshot(
        host="candidate-validation-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": entries or []}),
        ],
    )


def write_candidate_validation_fixture(root: Path) -> dict[str, Path]:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    installed_exe = root / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    installed_absent = root / "Applications" / "Absent Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_absent.parent.mkdir(parents=True)
    missing_clone = root / "private" / "var" / "folders" / "xx" / "com.google.Chrome.code_sign_clone" / "Contents" / "MacOS" / "Google Chrome"
    missing_normal = root / "Applications" / "Missing Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    archive = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": plistlib.UID(1)},
        "$objects": [
            "$null",
            {"ClientIdentities": plistlib.UID(2)},
            [plistlib.UID(3), plistlib.UID(5), plistlib.UID(7), plistlib.UID(9), plistlib.UID(11)],
            {"ClientIdentity": plistlib.UID(4), "State": "active"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_exe), "Kind": "client identity active"},
            {"ClientIdentity": plistlib.UID(6), "State": "installed absent"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_absent), "Kind": "client identity installed absent"},
            {"ClientIdentity": plistlib.UID(8), "State": "historical"},
            {"SigningIdentifier": "com.google.Chrome.code_sign_clone", "Path": str(missing_clone), "Kind": "client identity clone"},
            {"ClientIdentity": plistlib.UID(10), "State": "orphaned"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(missing_normal), "Kind": "client identity missing"},
            {"ClientIdentity": plistlib.UID(12), "State": "incomplete"},
            {"SigningIdentifier": "com.google.Chrome", "Kind": "client identity incomplete"},
        ],
    }
    with (prefs / "com.apple.networkextension.plist").open("wb") as handle:
        plistlib.dump(archive, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    (prefs / "com.apple.networkextension.malformed.plist").write_bytes(b"not a plist com.google.Chrome")
    return {
        "root": root,
        "installed_exe": installed_exe,
        "installed_absent": installed_absent,
        "missing_clone": missing_clone,
        "missing_normal": missing_normal,
    }


def test_candidate_validation_json_classifies_runtime_statuses_deterministically(tmp_path):
    fixture = write_candidate_validation_fixture(tmp_path / "ne")
    launchservices_entries = [{"bundle_identifier": "com.google.Chrome", "path": str(fixture["installed_exe"]), "generation_id": "chrome-active"}]
    first = build_networkextension_candidate_validation(
        [fixture["root"]],
        launchservices_entries=launchservices_entries,
        process_rows=[f"123 {fixture['installed_exe']} --type=browser"],
    ).to_json_dict()
    second = build_networkextension_candidate_validation(
        [fixture["root"]],
        launchservices_entries=launchservices_entries,
        process_rows=[f"123 {fixture['installed_exe']} --type=browser"],
    ).to_json_dict()

    assert first == second
    assert list(first)[:8] == [
        "command",
        "candidate_validation_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "summary",
        "validations",
        "decoded_artifacts",
    ]
    assert first["command"] == "networkextension validate-candidates"
    assert first["read_only"] is True
    assert first["mutation_performed"] is False
    assert first["summary"]["total_candidates"] == 5
    assert first["summary"]["status_counts"] == {
        "active_installed_app": 1,
        "runtime_absent": 1,
        "stale_code_sign_clone": 1,
        "stale_missing_executable": 1,
        "unverifiable": 1,
    }

    by_ref = {item["object_ref"]: item for item in first["validations"]}
    active = by_ref["$objects[4]"]
    assert active["candidate_status"] == "active_installed_app"
    assert active["evidence"]["executable_exists"] is True
    assert active["evidence"]["parent_bundle_exists"] is True
    assert active["evidence"]["installed_app_exists"] is True
    assert active["evidence"]["launchservices_generation_match"] is True
    assert active["evidence"]["running_process_match"] is True
    assert active["actionability"] == {
        "still_read_only": True,
        "requires_manual_confirmation": True,
        "never_auto_delete": True,
    }

    absent = by_ref["$objects[6]"]
    assert absent["candidate_status"] == "runtime_absent"
    assert absent["evidence"]["parent_bundle_exists"] is True
    assert absent["evidence"]["executable_exists"] is False
    assert "runtime absence alone is insufficient for automatic deletion" in absent["explanation"]

    clone = by_ref["$objects[8]"]
    assert clone["candidate_status"] == "stale_code_sign_clone"
    assert clone["evidence"]["path_is_code_sign_clone"] is True
    assert clone["evidence"]["path_is_temp_container"] is True

    missing = by_ref["$objects[10]"]
    assert missing["candidate_status"] == "stale_missing_executable"
    assert missing["evidence"]["executable_exists"] is False

    incomplete = by_ref["$objects[12]"]
    assert incomplete["candidate_status"] == "unverifiable"
    assert "insufficient" in incomplete["explanation"]


def test_validate_candidates_cli_text_is_read_only(monkeypatch, tmp_path):
    fixture = write_candidate_validation_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])

    result = CliRunner().invoke(app, ["networkextension", "validate-candidates", "--root", str(fixture["root"])])

    assert result.exit_code == 0
    assert "NetworkExtension candidate runtime validation" in result.stdout
    assert "Read-only: true" in result.stdout
    assert "Mutation performed: false" in result.stdout
    assert "runtime absence alone is insufficient for automatic deletion" in result.stdout
    forbidden = ["defaults write", "defaults delete", "lsregister", "killall", "rm ", "reset", "delete automatically"]
    lowered = result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_report_bundle_and_diff_include_candidate_validation(monkeypatch, tmp_path):
    fixture = write_candidate_validation_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [fixture["root"]])
    monkeypatch.setattr("macos_state_explorer.networkextension_candidate_validation._process_rows", lambda: [])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_candidate_validation_summary"]["total_candidates"] == 5
    assert "NetworkExtension candidate runtime validation" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-candidate-validation.json").exists()
    assert (bundle / "networkextension-candidate-validation.txt").exists()
    artifact = json.loads((bundle / "networkextension-candidate-validation.json").read_text())
    assert artifact["summary"]["total_candidates"] == 5

    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_candidate_validation_summary": {
            "candidate_refs": ["a:$objects[4]"],
            "status_counts": {"runtime_absent": 1},
            "runtime_absent_records": 1,
            "stale_records": 0,
        },
    }
    after_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_candidate_validation_summary": {
            "candidate_refs": ["a:$objects[4]", "a:$objects[8]"],
            "status_counts": {"stale_code_sign_clone": 1},
            "runtime_absent_records": 0,
            "stale_records": 1,
        },
    }
    (before / "report.json").write_text(json.dumps(before_report, sort_keys=True))
    (after / "report.json").write_text(json.dumps(after_report, sort_keys=True))

    diff_json = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    assert diff_json.exit_code == 0
    diff = json.loads(diff_json.stdout)
    assert diff["networkextension_candidate_validation_diff"]["added_candidate_refs"] == ["a:$objects[8]"]
    assert diff["networkextension_candidate_validation_diff"]["changed_statuses"] == ["runtime_absent", "stale_code_sign_clone"]
    diff_text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Candidate Validation Diff" in diff_text
    assert "Added candidate refs: a:$objects[8]" in diff_text
