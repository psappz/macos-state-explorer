from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def write_networkextension_fixture(root: Path) -> Path:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    (prefs / "com.apple.networkextension.plist").write_text(
        "\n".join(
            [
                "Chrome com.google.Chrome TEAMID EQHXZ8M8AV ApplicationUUID 11111111-1111-1111-1111-111111111111",
                "Edge com.microsoft.Edge TEAMID UBF8T346G9 ApplicationUUID 22222222-2222-2222-2222-222222222222",
                "SecurityPrivacyExtension System Settings LaunchServices identity com.google.GoogleUpdater",
            ]
        )
    )
    (prefs / "com.apple.networkextension.plist").touch()
    (prefs / "com.apple.networkextension.localnetwork.json").write_text(
        json.dumps(
            {
                "apps": [
                    {
                        "bundle_id": "com.google.Chrome",
                        "path": "/Applications/Google Chrome.app",
                        "application_uuid": "11111111-1111-1111-1111-111111111111",
                        "team_id": "EQHXZ8M8AV",
                        "authorization": "allowed",
                    }
                ],
                "generation": 7,
            },
            sort_keys=True,
        )
    )
    return root


def snapshot_with_launchservices() -> Snapshot:
    return Snapshot(
        host="ne-state-host",
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
                            "raw_block": "Chrome",
                            "bundle_id": "com.google.Chrome",
                            "identifier": "com.google.Chrome",
                            "canonical_id": "com.google.Chrome",
                            "name": "Google Chrome",
                            "display_name": "Google Chrome",
                            "version": "149.0.1",
                            "display_version": "149.0.1",
                            "path": "/Applications/Google Chrome.app",
                            "path_clean": "/Applications/Google Chrome.app",
                            "path_exists": True,
                            "volume": "/",
                            "volume_exists": True,
                            "classification": "ACTIVE",
                        }
                    ]
                },
            ),
        ],
    )


def test_networkextension_state_json_is_deterministic_and_read_only(tmp_path):
    root = write_networkextension_fixture(tmp_path / "fixtures")

    first = CliRunner().invoke(app, ["networkextension", "state", "--root", str(root), "--json"])
    second = CliRunner().invoke(app, ["networkextension", "state", "--root", str(root), "--json"])

    assert first.exit_code == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert list(payload)[:8] == [
        "command",
        "state_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "summary",
        "artifacts",
        "observations",
    ]
    assert payload["command"] == "networkextension state"
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["summary"]["artifact_count"] == 2
    assert payload["summary"]["unknown_count"] >= 1
    assert payload["summary"]["references"] == {
        "Chrome": 2,
        "Chromium": 0,
        "Edge": 1,
        "GoogleUpdater": 1,
        "LaunchServices": 1,
        "SecurityPrivacyExtension": 1,
        "System Settings": 1,
    }
    assert payload["artifacts"][0]["observation_state"] == "Observed"
    assert payload["observations"][0]["classification"] in {"Observed", "Unknown"}
    rendered = json.dumps(payload).lower()
    assert not any(token in rendered for token in ["rm -", "sudo", "defaults write", "plutil -replace", "tccutil reset", "killall", "reboot"])


def test_networkextension_state_human_output(tmp_path):
    root = write_networkextension_fixture(tmp_path / "fixtures")

    result = CliRunner().invoke(app, ["networkextension", "state", "--root", str(root)])

    assert result.exit_code == 0
    assert "NetworkExtension state" in result.stdout
    assert "Read-only: true" in result.stdout
    assert "Observed artifacts: 2" in result.stdout
    assert "Chrome references: 2" in result.stdout
    assert "Unknown" in result.stdout


def test_networkextension_state_handles_missing_artifacts_as_unknown(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()

    result = CliRunner().invoke(app, ["networkextension", "state", "--root", str(root), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["artifact_count"] == 0
    assert payload["summary"]["unknown_count"] > 0
    assert {item["name"] for item in payload["observations"] if item["classification"] == "Unknown"} >= {
        "NetworkExtension preference files",
        "Local Network preference stores",
        "per-app authorization records",
        "signing identities",
    }


def test_local_network_report_and_bundle_include_networkextension_state(monkeypatch, tmp_path):
    root = write_networkextension_fixture(tmp_path / "fixtures")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [root])
    snap = snapshot_with_launchservices()
    report = build_local_network_report(snap)

    payload = report.to_json_dict()
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")

    assert payload["networkextension_state_summary"]["artifact_count"] == 2
    assert "NetworkExtension state" in report.render_text()
    assert (bundle / "networkextension-state.json").exists()
    assert (bundle / "networkextension-state.txt").exists()
    assert json.loads((bundle / "networkextension-state.json").read_text())["command"] == "networkextension state"


def test_bundle_diff_includes_networkextension_state_changes(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "networkextension_state_summary": {
                    "artifact_paths": ["Library/Preferences/com.apple.networkextension.plist"],
                    "bundle_ids": ["com.google.Chrome"],
                    "application_uuids": ["11111111-1111-1111-1111-111111111111"],
                    "references": {"Chrome": 1, "Edge": 0},
                    "unknown_items": ["signing identities"],
                },
            }
        )
    )
    (after / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "networkextension_state_summary": {
                    "artifact_paths": ["Library/Preferences/com.apple.networkextension.plist", "Library/Preferences/com.apple.networkextension.localnetwork.json"],
                    "bundle_ids": ["com.google.Chrome", "com.microsoft.Edge"],
                    "application_uuids": ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
                    "references": {"Chrome": 2, "Edge": 1},
                    "unknown_items": [],
                },
            }
        )
    )

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["networkextension_state_diff"] == {
        "added_artifacts": ["Library/Preferences/com.apple.networkextension.localnetwork.json"],
        "removed_artifacts": [],
        "added_bundle_ids": ["com.microsoft.Edge"],
        "removed_bundle_ids": [],
        "added_application_uuids": ["22222222-2222-2222-2222-222222222222"],
        "removed_application_uuids": [],
        "changed_references": ["Chrome", "Edge"],
        "resolved_unknown_items": ["signing identities"],
        "new_unknown_items": [],
    }


def test_diff_bundles_renders_networkextension_state_human_output(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_state_summary": {"artifact_paths": [], "bundle_ids": [], "application_uuids": [], "references": {}, "unknown_items": ["NetworkExtension preference files"]}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "networkextension_state_summary": {"artifact_paths": ["Library/Preferences/com.apple.networkextension.plist"], "bundle_ids": ["com.google.Chrome"], "application_uuids": [], "references": {"Chrome": 1}, "unknown_items": []}}))

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)])

    assert result.exit_code == 0
    assert "NetworkExtension State Diff" in result.stdout
    assert "Added artifacts: Library/Preferences/com.apple.networkextension.plist" in result.stdout
    assert "Added bundle IDs: com.google.Chrome" in result.stdout


def test_solve_local_network_includes_networkextension_summary(monkeypatch, tmp_path):
    root = write_networkextension_fixture(tmp_path / "fixtures")
    monkeypatch.setattr("macos_state_explorer.solver.local_network.default_networkextension_roots", lambda: [root])

    solution = __import__("macos_state_explorer.solver.local_network", fromlist=["build_local_network_solution"]).build_local_network_solution(snapshot_with_launchservices())

    assert solution.networkextension_state_summary["artifact_count"] == 2
    assert solution.to_json_dict()["networkextension_state_summary"]["references"]["Chrome"] == 2
