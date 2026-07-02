from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def snapshot_with_launchservices() -> Snapshot:
    return Snapshot(
        host="raw-reference-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entries": [
                        {
                            "raw_block": "Google Chrome com.google.Chrome",
                            "bundle_id": "com.google.Chrome",
                            "identifier": "com.google.Chrome",
                            "canonical_id": "com.google.Chrome",
                            "name": "Google Chrome",
                            "display_name": "Google Chrome",
                            "version": "149.0.1",
                            "display_version": "149.0.1",
                            "path": "/Applications/Google Chrome.app",
                            "path_clean": "/Applications/Google Chrome.app",
                            "path_exists": False,
                            "executable": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                            "team_id": "EQHXZ8M8AV",
                            "classification": "STALE",
                            "fields": {"application_uuid": "11111111-1111-1111-1111-111111111111"},
                        }
                    ]
                },
            ),
        ],
    )


def write_raw_reference_fixture(root: Path) -> Path:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    (prefs / "com.apple.networkextension.localnetwork.json").write_text(
        json.dumps(
            {
                "LocalNetwork": {
                    "Applications": {
                        "GoogleChrome": {
                            "bundleID": "com.google.Chrome",
                            "path": "/Applications/Google Chrome.app",
                            "note": "SecurityPrivacyExtension showed com.google.Chrome.code_sign_clone in Local Network",
                        }
                    }
                },
                "raw_blob": " ".join(
                    [
                        "cache blob",
                        "com.google.Chrome",
                        "com.google.Chrome.code_sign_clone",
                        "/Users/psi/.Trash/Google Chrome.app",
                        "LaunchServices",
                        "SecurityPrivacyExtension",
                        "Chromium helper text",
                        "99999999-9999-9999-9999-999999999999",
                        "EQHXZ8M8AV",
                    ]
                ),
            },
            sort_keys=True,
        )
    )
    (prefs / "com.apple.securityprivacyextension.cache.json").write_text(
        json.dumps(
            {
                "cache": "broad serialized cache mentions com.google.Chrome com.google.Chrome.code_sign_clone Chromium LaunchServices SecurityPrivacyExtension",
            },
            sort_keys=True,
        )
    )
    return root


def test_networkextension_raw_references_json_attributes_key_path_and_categories(tmp_path):
    root = write_raw_reference_fixture(tmp_path / "ne")

    first = CliRunner().invoke(app, ["networkextension", "raw-references", "--root", str(root), "--json"])
    second = CliRunner().invoke(app, ["networkextension", "raw-references", "--root", str(root), "--json"])

    assert first.exit_code == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert list(payload)[:8] == [
        "command",
        "raw_reference_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "summary",
        "references",
        "roots",
    ]
    assert payload["command"] == "networkextension raw-references"
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    summary = payload["summary"]
    assert summary["total_raw_references"] >= 8
    assert summary["artifacts_with_chrome_references"] == 2
    assert summary["candidate_local_network_store_references"] >= 1
    assert summary["broad_cache_or_blob_references"] >= 1
    assert summary["structurally_bound_references"] >= 1
    assert summary["non_actionable_references"] >= 1

    refs = payload["references"]
    by_token = {(item["matched_token"], item["plist_key_path"]): item for item in refs}
    chrome_bundle = by_token[("com.google.Chrome", "LocalNetwork.Applications.GoogleChrome.bundleID")]
    assert chrome_bundle["reference_category"] == "chrome_bundle_id"
    assert chrome_bundle["binding_status"] == "structurally_bound_identity"
    assert chrome_bundle["safety_classification"] == "candidate_local_network_store"
    assert "specific Local Network preference key" in chrome_bundle["actionability_reason"]

    clone_refs = [item for item in refs if item["matched_token"] == "com.google.Chrome.code_sign_clone"]
    assert {item["reference_category"] for item in clone_refs} == {"chrome_code_sign_clone"}

    raw_refs = [item for item in refs if item["plist_key_path"] == "raw_blob"]
    assert raw_refs
    assert all(item["binding_status"] == "raw_text_reference_only" for item in raw_refs)
    assert all(item["safety_classification"] in {"broad_cache_or_blob", "inspect_only", "not_actionable"} for item in raw_refs)
    assert all("99999999-9999-9999-9999-999999999999" not in item["surrounding_context"] for item in raw_refs)
    assert all("EQHXZ8M8AV" not in item["surrounding_context"] for item in raw_refs)


def test_networkextension_raw_references_human_output_is_read_only_and_explains_non_actionable(tmp_path):
    root = write_raw_reference_fixture(tmp_path / "ne")

    result = CliRunner().invoke(app, ["networkextension", "raw-references", "--root", str(root)])

    assert result.exit_code == 0
    assert "NetworkExtension raw references" in result.stdout
    assert "Read-only: true" in result.stdout
    assert "Mutation performed: false" in result.stdout
    assert "chrome_code_sign_clone" in result.stdout
    assert "broad_cache_or_blob" in result.stdout
    assert "does not create identity binding" in result.stdout
    forbidden = ["defaults write", "defaults delete", "lsregister", "killall", "rm ", "repair", "reset"]
    lowered = result.stdout.lower()
    for token in forbidden:
        assert token not in lowered


def test_local_network_report_and_bundle_include_raw_references(monkeypatch, tmp_path):
    root = write_raw_reference_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [root])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_raw_references_summary"]["total_raw_references"] >= 8
    assert "NetworkExtension raw references" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-raw-references.json").exists()
    assert (bundle / "networkextension-raw-references.txt").exists()
    artifact = json.loads((bundle / "networkextension-raw-references.json").read_text())
    assert artifact["summary"]["broad_cache_or_blob_references"] >= 1


def test_bundle_diff_includes_networkextension_raw_references_diff(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "networkextension_raw_references_summary": {
                    "total_raw_references": 3,
                    "artifacts_with_chrome_references": 1,
                    "candidate_local_network_store_references": 0,
                    "broad_cache_or_blob_references": 3,
                    "structurally_bound_references": 0,
                    "non_actionable_references": 3,
                },
            },
            sort_keys=True,
        )
    )
    (after / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "networkextension_raw_references_summary": {
                    "total_raw_references": 5,
                    "artifacts_with_chrome_references": 2,
                    "candidate_local_network_store_references": 1,
                    "broad_cache_or_blob_references": 4,
                    "structurally_bound_references": 1,
                    "non_actionable_references": 4,
                },
            },
            sort_keys=True,
        )
    )

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["networkextension_raw_references_diff"] == {
        "total_raw_references_delta": 2,
        "artifacts_with_chrome_references_delta": 1,
        "candidate_local_network_store_references_delta": 1,
        "broad_cache_or_blob_references_delta": 1,
        "structurally_bound_references_delta": 1,
        "non_actionable_references_delta": 1,
    }

    text = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)]).stdout
    assert "NetworkExtension Raw References Diff" in text
    assert "Candidate Local Network store references: +1" in text
