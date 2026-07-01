from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticModule, DiagnosticSolution
from macos_state_explorer.diagnostics.launchservices.module import LAUNCHSERVICES_MODULE
from macos_state_explorer.reports.launchservices import build_launchservices_report, write_launchservices_support_bundle
from macos_state_explorer.solver.launchservices import build_launchservices_solution


def _snapshot() -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entry_count": 4,
                    "classification_counts": {"ACTIVE": 1, "STALE": 1, "ORPHANED": 1, "UNKNOWN": 1},
                    "entries": [
                        {
                            "raw_block": "Chrome active",
                            "bundle_id": "com.google.Chrome",
                            "display_name": "Google Chrome",
                            "path": "/Applications/Google Chrome.app",
                            "path_clean": "/Applications/Google Chrome.app",
                            "path_exists": True,
                            "classification": "ACTIVE",
                        },
                        {
                            "raw_block": "Chrome stale",
                            "bundle_id": "com.google.Chrome",
                            "display_name": "Google Chrome old",
                            "path": "/Volumes/OldDisk/Google Chrome.app",
                            "path_clean": "/Volumes/OldDisk/Google Chrome.app",
                            "path_exists": False,
                            "node_not_found": True,
                            "classification": "STALE",
                        },
                        {
                            "raw_block": "Missing app",
                            "bundle_id": "com.example.Missing",
                            "display_name": "Missing App",
                            "path": "/Applications/Missing.app",
                            "path_clean": "/Applications/Missing.app",
                            "path_exists": False,
                            "classification": "ORPHANED",
                        },
                        {
                            "raw_block": "Unknown helper",
                            "bundle_id": "com.example.Helper",
                            "display_name": "Helper",
                            "path": "/tmp/Helper.app",
                            "path_clean": "/tmp/Helper.app",
                            "path_exists": None,
                            "classification": "UNKNOWN",
                        },
                    ],
                    "stale_entries": [
                        {
                            "raw_block": "Chrome stale",
                            "bundle_id": "com.google.Chrome",
                            "display_name": "Google Chrome old",
                            "path": "/Volumes/OldDisk/Google Chrome.app",
                            "path_clean": "/Volumes/OldDisk/Google Chrome.app",
                            "path_exists": False,
                            "node_not_found": True,
                            "classification": "STALE",
                        },
                        {
                            "raw_block": "Missing app",
                            "bundle_id": "com.example.Missing",
                            "display_name": "Missing App",
                            "path": "/Applications/Missing.app",
                            "path_clean": "/Applications/Missing.app",
                            "path_exists": False,
                            "classification": "ORPHANED",
                        },
                    ],
                    "candidate_files": {
                        "stdout": "/private/var/db/lsd/com.apple.LaunchServices-123.csstore\n"
                    },
                },
            )
        ],
    )


def test_launchservices_module_is_registered_as_framework_module():
    assert isinstance(LAUNCHSERVICES_MODULE, DiagnosticModule)
    assert LAUNCHSERVICES_MODULE.id == "launchservices"
    assert LAUNCHSERVICES_MODULE.command_name == "launchservices"
    assert LAUNCHSERVICES_MODULE.supporting_commands == (
        "mse launchservices ~/Desktop/mse-launchservices",
        "mse collect ~/Desktop/mse-launchservices-collect --fast",
    )


def test_launchservices_solution_uses_framework_contracts():
    solution = build_launchservices_solution(_snapshot())

    assert isinstance(solution, DiagnosticSolution)
    assert solution.command_name == "launchservices"
    assert [item.id for item in solution.evidence] == ["LS-E001", "LS-E002", "LS-E003", "LS-E004"]
    assert {item.id for item in solution.evidence if item.present} == {
        "LS-E001",
        "LS-E002",
        "LS-E003",
        "LS-E004",
    }
    assert solution.repair_plan[0].id == "review-stale-launchservices"
    assert solution.to_json_dict()["command"] == "solve launchservices"
    rendered = solution.render_text()
    assert "Current diagnosis" in rendered
    assert "LS-E001" in rendered
    assert "manual-reinstall-chrome" not in rendered
    assert "Local Network" not in rendered


def test_solve_launchservices_cli_json_and_human_output(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    json_result = runner.invoke(app, ["solve", "launchservices", "--json"])
    human_result = runner.invoke(app, ["solve", "launchservices"])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert list(payload) == ["command", "diagnosis", "evidence", "matched_rules", "repair_candidates", "next_action"]
    assert payload["command"] == "solve launchservices"
    assert payload["next_action"]["id"] == "review-stale-launchservices"
    assert human_result.exit_code == 0
    assert human_result.stdout.startswith("Current diagnosis")
    assert "Supporting read-only commands" in human_result.stdout


def test_report_launchservices_json_and_support_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()
    bundle = tmp_path / "bundle"

    result = runner.invoke(app, ["report", "launchservices", "--json", "--bundle", str(bundle)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload) == ["command", "solution", "supporting_commands", "bundle_schema_version"]
    assert payload["command"] == "report launchservices"
    assert payload["solution"]["command"] == "solve launchservices"
    assert sorted(path.name for path in bundle.iterdir()) == [
        "command.json",
        "environment.json",
        "report.json",
        "report.txt",
    ]
    assert json.loads((bundle / "report.json").read_text())["command"] == "report launchservices"
    assert "LaunchServices diagnostic report" in (bundle / "report.txt").read_text()


def test_launchservices_report_writer_reuses_framework_support_bundle(tmp_path):
    report = build_launchservices_report(_snapshot())
    bundle = write_launchservices_support_bundle(report, tmp_path / "support")

    assert bundle == tmp_path / "support"
    assert json.loads((bundle / "command.json").read_text())["command"] == "mse report launchservices --bundle"
    assert (bundle / "report.txt").read_text().startswith("LaunchServices diagnostic report")


def test_report_launchservices_bundle_rejects_file_path(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    target = tmp_path / "not-a-directory"
    target.write_text("occupied")
    runner = CliRunner()

    result = runner.invoke(app, ["report", "launchservices", "--bundle", str(target)])

    assert result.exit_code == 1
    assert "Bundle path exists and is not a directory" in result.stdout
