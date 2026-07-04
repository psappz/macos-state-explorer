from __future__ import annotations

import json
import plistlib
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices() -> Snapshot:
    return Snapshot(
        host="repair-candidate-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={"entries": []},
            ),
        ],
    )


def write_repair_candidate_fixture(root: Path) -> Path:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    installed_exe = root / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    installed_exe.parent.mkdir(parents=True)
    installed_exe.write_text("#!/bin/sh\n", encoding="utf-8")
    clone_only = root / "Library" / "Application Support" / "com.google.Chrome.code_sign_clone" / "Contents" / "MacOS" / "Google Chrome"
    clone_only.parent.mkdir(parents=True)
    clone_only.write_text("#!/bin/sh\n", encoding="utf-8")
    missing = root / "Applications" / "Missing Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    archive = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": plistlib.UID(1)},
        "$objects": [
            "$null",
            {"LocalNetworkPolicies": plistlib.UID(2), "HistoricalClientArchive": plistlib.UID(10), "Incomplete": plistlib.UID(12)},
            [plistlib.UID(3), plistlib.UID(6), plistlib.UID(8)],
            {"ClientIdentity": plistlib.UID(4), "State": "active"},
            {"SigningIdentifier": "com.google.Chrome", "Path": plistlib.UID(5), "Kind": "client identity"},
            str(installed_exe),
            {"ClientIdentity": plistlib.UID(7), "State": "active"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(installed_exe), "Kind": "client identity duplicate"},
            {"ClientIdentity": plistlib.UID(9), "State": "orphaned"},
            {"SigningIdentifier": "com.google.Chrome", "Path": str(missing), "Kind": "client identity orphaned"},
            {"ClientIdentity": plistlib.UID(11), "Historical": True},
            {"SigningIdentifier": "com.google.Chrome.code_sign_clone", "Path": str(clone_only), "Kind": "client identity historical clone"},
            {"SigningIdentifier": "com.google.Chrome", "Kind": "client identity incomplete"},
        ],
    }
    with (prefs / "com.apple.networkextension.plist").open("wb") as handle:
        plistlib.dump(archive, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
    (prefs / "com.apple.networkextension.malformed.plist").write_bytes(b"not a plist com.google.Chrome")
    return root


def test_networkextension_repair_candidates_json_classifies_client_identity_records(tmp_path):
    root = write_repair_candidate_fixture(tmp_path / "ne")

    first = CliRunner().invoke(app, ["networkextension", "repair-candidates", "--root", str(root), "--json"])
    second = CliRunner().invoke(app, ["networkextension", "repair-candidates", "--root", str(root), "--json"])

    assert first.exit_code == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert list(payload)[:8] == [
        "command",
        "repair_candidates_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "summary",
        "candidates",
        "decoded_artifacts",
    ]
    assert payload["command"] == "networkextension repair-candidates"
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["summary"]["total_candidates"] == 5
    assert payload["summary"]["duplicate_records"] == 2
    assert payload["summary"]["installed_application_references"] >= 2
    assert payload["summary"]["code_sign_clone_only_records"] == 1
    assert payload["summary"]["orphaned_records"] >= 1
    assert payload["summary"]["malformed_artifacts"] == 1

    candidates = payload["candidates"]
    installed = next(item for item in candidates if item["object_reference"] == "$objects[4]")
    assert installed["identity_type"] == "client_identity_record"
    assert installed["signing_identifier"] == "com.google.Chrome"
    assert installed["executable_exists"] is True
    assert installed["references_installed_application"] is True
    assert installed["appears_complete"] is True
    assert installed["appears_duplicated"] is True
    assert installed["appears_active"] is True
    assert installed["could_ever_be_safely_removed"] is False
    assert installed["additional_runtime_evidence_required"] is True
    assert installed["safety_classification"] == "requires_runtime_confirmation"
    assert "never automatically delete" in installed["explanation"]

    clone = next(item for item in candidates if item["references_only_code_sign_clone"])
    assert clone["signing_identifier"] == "com.google.Chrome.code_sign_clone"
    assert clone["code_sign_clone_usage"] is True
    assert clone["appears_historical"] is True
    assert clone["safety_classification"] in {"manual_only", "potential_future_repair_candidate"}
    assert clone["additional_runtime_evidence_required"] is True

    missing = next(item for item in candidates if "Missing Chrome.app" in (item["executable_path"] or ""))
    assert missing["executable_exists"] is False
    assert missing["appears_orphaned"] is True
    assert missing["safety_classification"] == "potential_future_repair_candidate"

    incomplete = next(item for item in candidates if item["object_reference"] == "$objects[12]")
    assert incomplete["appears_complete"] is False
    assert incomplete["safety_classification"] == "not_actionable"
    assert "insufficient" in incomplete["explanation"]


def test_networkextension_repair_candidates_human_output_is_read_only(tmp_path):
    root = write_repair_candidate_fixture(tmp_path / "ne")

    result = CliRunner().invoke(app, ["networkextension", "repair-candidates", "--root", str(root)])

    assert result.exit_code == 0
    assert "NetworkExtension repair candidates" in result.stdout
    assert "Read-only: true" in result.stdout
    assert "Mutation performed: false" in result.stdout
    assert "requires_runtime_confirmation" in result.stdout
    assert "never automatically delete" in result.stdout
    forbidden = ["defaults write", "defaults delete", "lsregister", "killall", "rm ", "reset", "delete automatically"]
    lowered = result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_local_network_report_and_bundle_include_repair_candidates(monkeypatch, tmp_path):
    root = write_repair_candidate_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [root])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_repair_candidates_summary"]["total_candidates"] == 5
    assert "NetworkExtension repair candidates" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-repair-candidates.json").exists()
    assert (bundle / "networkextension-repair-candidates.txt").exists()
    artifact = json.loads((bundle / "networkextension-repair-candidates.json").read_text())
    assert artifact["summary"]["duplicate_records"] == 2


def test_bundle_diff_includes_networkextension_repair_candidate_diff(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_candidates_summary": {
            "candidate_object_refs": ["com.apple.networkextension.plist:$objects[4]"],
            "safety_classifications": {"requires_runtime_confirmation": 1},
            "duplicate_records": 0,
            "orphaned_records": 0,
            "code_sign_clone_only_records": 0,
        },
    }
    after_report = {
        "command": "report local-network",
        "evidence": [],
        "networkextension_repair_candidates_summary": {
            "candidate_object_refs": ["com.apple.networkextension.plist:$objects[4]", "com.apple.networkextension.plist:$objects[9]"],
            "safety_classifications": {"potential_future_repair_candidate": 1},
            "duplicate_records": 1,
            "orphaned_records": 1,
            "code_sign_clone_only_records": 1,
        },
    }
    (before / "report.json").write_text(json.dumps(before_report, sort_keys=True))
    (after / "report.json").write_text(json.dumps(after_report, sort_keys=True))

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["networkextension_repair_candidate_diff"] == {
        "added_candidate_object_refs": ["com.apple.networkextension.plist:$objects[9]"],
        "removed_candidate_object_refs": [],
        "changed_safety_classifications": ["potential_future_repair_candidate", "requires_runtime_confirmation"],
        "duplicate_records_delta": 1,
        "orphaned_records_delta": 1,
        "code_sign_clone_only_records_delta": 1,
    }

    text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Repair Candidate Diff" in text
    assert "Added candidate object refs: com.apple.networkextension.plist:$objects[9]" in text
