from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


UUID_CONFIRMED = "11111111-1111-1111-1111-111111111111"
UUID_CONFLICT_LS = "22222222-2222-2222-2222-222222222222"
UUID_CONFLICT_NE = "33333333-3333-3333-3333-333333333333"
UUID_PROBABLE = "44444444-4444-4444-4444-444444444444"


def write_networkextension_identity_fixture(root: Path) -> Path:
    prefs = root / "Library" / "Preferences"
    prefs.mkdir(parents=True)
    (prefs / "com.apple.networkextension.localnetwork.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "bundle_id": "com.google.Chrome",
                        "application_uuid": UUID_CONFIRMED,
                        "team_id": "EQHXZ8M8AV",
                        "path": "/Applications/Google Chrome.app",
                        "authorization": "allowed",
                    },
                    {
                        "bundle_id": "com.google.Chrome.Beta",
                        "application_uuid": UUID_CONFLICT_NE,
                        "team_id": "ZZZZZZZZZZ",
                        "path": "/Applications/Conflicting Chrome.app",
                        "authorization": "allowed",
                    },
                    {
                        "bundle_id": "com.google.Chrome.Dev",
                        "team_id": "EQHXZ8M8AV",
                        "path": "/Applications/Google Chrome Dev.app",
                        "authorization": "prompted",
                    },
                ],
                "SecurityPrivacyExtension": "Chrome identity shown in System Settings",
                "generation": 9,
            },
            sort_keys=True,
        )
    )
    return root


def trace_identity_fixture(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "analysis.json").write_text(
        json.dumps(
            {
                "events": [
                    {
                        "process": "SecurityPrivacyExtension",
                        "bundle_id": "com.google.Chrome",
                        "application_uuid": UUID_CONFIRMED,
                        "path": "/Applications/Google Chrome.app",
                        "runningboard_identity": "RBIdentity<com.google.Chrome>",
                    },
                    {
                        "process": "runningboardd",
                        "bundle_id": "com.google.Chrome.Dev",
                        "path": "/Applications/Google Chrome Dev.app",
                        "runningboard_identity": "RBIdentity<com.google.Chrome.Dev>",
                    },
                ]
            },
            sort_keys=True,
        )
    )
    return path


def launchservices_entries() -> list[dict[str, object]]:
    return [
        _ls_record("com.google.Chrome", "Google Chrome", "149.0.1", "/Applications/Google Chrome.app", UUID_CONFIRMED, "EQHXZ8M8AV"),
        _ls_record("com.google.Chrome.Beta", "Google Chrome Beta", "149.0.2", "/Applications/Google Chrome Beta.app", UUID_CONFLICT_LS, "EQHXZ8M8AV"),
        _ls_record("com.google.Chrome.Dev", "Google Chrome Dev", "149.0.3", "/Applications/Google Chrome Dev.app", UUID_PROBABLE, "EQHXZ8M8AV"),
        _ls_record("com.google.Chrome.Canary", "Google Chrome Canary", "149.0.4", "/Applications/Google Chrome Canary.app", None, None),
    ]


def _ls_record(bundle_id: str, name: str, version: str, path: str, uuid: str | None, team_id: str | None) -> dict[str, object]:
    fields = {}
    if uuid:
        fields["application_uuid"] = uuid
    return {
        "raw_block": f"{name} {bundle_id} {uuid or ''}",
        "bundle_id": bundle_id,
        "identifier": bundle_id,
        "canonical_id": bundle_id,
        "name": name,
        "display_name": name,
        "version": version,
        "display_version": version,
        "path": path,
        "path_clean": path,
        "path_exists": False,
        "executable": f"{path}/Contents/MacOS/{name}",
        "team_id": team_id,
        "classification": "STALE",
        "fields": fields,
    }


def snapshot_with_launchservices() -> Snapshot:
    return Snapshot(
        host="identity-host",
        created_at=123.0,
        observations=[
            Observation(collector="tcc", started_at=1, ended_at=2, payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}}),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"entries": launchservices_entries()}),
        ],
    )


def test_networkextension_correlate_json_builds_deterministic_identity_graph(monkeypatch, tmp_path):
    root = write_networkextension_identity_fixture(tmp_path / "ne")
    trace = trace_identity_fixture(tmp_path / "trace")
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=True: snapshot_with_launchservices())

    first = CliRunner().invoke(app, ["networkextension", "correlate", "--root", str(root), "--trace", str(trace), "--json"])
    second = CliRunner().invoke(app, ["networkextension", "correlate", "--root", str(root), "--trace", str(trace), "--json"])

    assert first.exit_code == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)
    payload = json.loads(first.stdout)
    assert list(payload)[:8] == [
        "command",
        "correlation_id",
        "timestamp",
        "read_only",
        "mutation_performed",
        "summary",
        "identity_graph",
        "generation_correlations",
    ]
    assert payload["command"] == "networkextension correlate"
    assert payload["read_only"] is True
    assert payload["mutation_performed"] is False
    assert payload["summary"] == {
        "generation_count": 4,
        "confirmed_identical": 1,
        "probable_identical": 1,
        "conflicting_identity": 1,
        "no_observable_relationship": 1,
        "unknown": 0,
        "read_only": True,
        "mutation_performed": False,
    }
    by_bundle = {item["bundle_identifier"]: item for item in payload["generation_correlations"]}
    assert by_bundle["com.google.Chrome"]["relationship"] == "confirmed_identical"
    assert by_bundle["com.google.Chrome"]["evidence_basis"] == [
        "Observed: shared application UUID",
        "Observed: shared bundle identifier",
        "Observed: shared executable path",
        "Observed: shared Team ID",
        "Observed: shared trace identity",
    ]
    assert by_bundle["com.google.Chrome.Beta"]["relationship"] == "conflicting_identity"
    assert by_bundle["com.google.Chrome.Beta"]["conflicts"] == [
        "application_uuid: LaunchServices=22222222-2222-2222-2222-222222222222 NetworkExtension=33333333-3333-3333-3333-333333333333",
        "executable_path: LaunchServices=/Applications/Google Chrome Beta.app NetworkExtension=/Applications/Conflicting Chrome.app",
        "team_id: LaunchServices=EQHXZ8M8AV NetworkExtension=ZZZZZZZZZZ",
    ]
    assert by_bundle["com.google.Chrome.Dev"]["relationship"] == "probable_identical"
    assert by_bundle["com.google.Chrome.Canary"]["relationship"] == "no_observable_relationship"
    assert by_bundle["com.google.Chrome.Canary"]["missing_evidence"] == [
        "NetworkExtension preference entry",
        "application UUID",
        "Team ID",
        "trace identity",
    ]
    assert payload["identity_graph"]["edges"][0]["evidence_class"] in {"Observed", "Correlated"}


def test_networkextension_correlate_human_output(monkeypatch, tmp_path):
    root = write_networkextension_identity_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=True: snapshot_with_launchservices())

    result = CliRunner().invoke(app, ["networkextension", "correlate", "--root", str(root)])

    assert result.exit_code == 0
    assert "NetworkExtension identity correlation" in result.stdout
    assert "Read-only: true" in result.stdout
    assert "Mutation performed: false" in result.stdout
    assert "confirmed_identical: 1" in result.stdout
    assert "conflicting_identity: 1" in result.stdout
    assert "com.google.Chrome.Beta → conflicting_identity" in result.stdout
    assert "Observed: shared bundle identifier" in result.stdout
    assert "Unknown" in result.stdout


def test_local_network_report_and_bundle_include_networkextension_correlation(monkeypatch, tmp_path):
    root = write_networkextension_identity_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.reports.local_network.default_networkextension_roots", lambda: [root])
    report = build_local_network_report(snapshot_with_launchservices())

    payload = report.to_json_dict()
    assert payload["networkextension_correlation_summary"]["confirmed_identical"] == 1
    assert "NetworkExtension identity correlation" in report.render_text()

    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="manual-empty-trash-reboot")
    assert (bundle / "networkextension-correlation.json").exists()
    assert (bundle / "networkextension-correlation.txt").exists()
    artifact = json.loads((bundle / "networkextension-correlation.json").read_text())
    assert artifact["summary"]["conflicting_identity"] == 1


def test_bundle_diff_includes_networkextension_correlation_diff(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "evidence": [],
                "networkextension_correlation_summary": {
                    "generation_ids": ["chrome:149.0.4:/Applications/Google Chrome Canary.app"],
                    "confirmed_generation_ids": [],
                    "conflicting_generation_ids": [],
                    "unknown_generation_ids": ["chrome:149.0.4:/Applications/Google Chrome Canary.app"],
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
                "networkextension_correlation_summary": {
                    "generation_ids": ["chrome:149.0.4:/Applications/Google Chrome Canary.app"],
                    "confirmed_generation_ids": ["chrome:149.0.4:/Applications/Google Chrome Canary.app"],
                    "conflicting_generation_ids": [],
                    "unknown_generation_ids": [],
                },
            },
            sort_keys=True,
        )
    )

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["networkextension_correlation_diff"] == {
        "newly_confirmed_generations": ["chrome:149.0.4:/Applications/Google Chrome Canary.app"],
        "new_conflicting_generations": [],
        "resolved_unknown_generations": ["chrome:149.0.4:/Applications/Google Chrome Canary.app"],
        "added_generations": [],
        "removed_generations": [],
    }


def test_networkextension_correlation_output_does_not_suggest_mutation(monkeypatch, tmp_path):
    root = write_networkextension_identity_fixture(tmp_path / "ne")
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=True: snapshot_with_launchservices())

    result = CliRunner().invoke(app, ["networkextension", "correlate", "--root", str(root)])

    assert result.exit_code == 0
    forbidden = ["rm ", "delete", "repair", "reset", "rebuild", "tccutil", "sqlite3", "killall", "mutation performed: true"]
    lowered = result.stdout.lower()
    for token in forbidden:
        assert token not in lowered
