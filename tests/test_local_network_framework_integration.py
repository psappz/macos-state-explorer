from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticRegistry, FrameworkDiagnosticEngine
from macos_state_explorer.diagnostics.local_network.module import LOCAL_NETWORK_MODULE
from macos_state_explorer.solver.local_network import build_local_network_solution


def _snapshot() -> Snapshot:
    return Snapshot(
        host="framework-ln-host",
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}},
            ),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "stale_entries": [
                        {"bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app"},
                        {"bundle_id": "com.google.Chrome.code_sign_clone", "path": "/Applications/Google Chrome.app"},
                    ],
                    "entries": [
                        {
                            "bundle_id": "com.google.Chrome",
                            "path": "/Applications/Google Chrome.app",
                            "classification": "STALE",
                        }
                    ],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices.csstore\n"},
                },
            ),
        ],
    )


def test_local_network_registered_module_matches_public_solver_contract():
    registry = DiagnosticRegistry([LOCAL_NETWORK_MODULE])
    framework_solution = FrameworkDiagnosticEngine(registry.get("local-network")).solve(_snapshot())
    public_solution = build_local_network_solution(_snapshot())

    assert framework_solution.to_json_dict() == public_solution.to_json_dict()
    assert framework_solution.render_text() == public_solution.render_text()
    assert [candidate.id for candidate in framework_solution.repair_plan] == ["manual-reinstall-chrome", "trace-local-network"]


def test_solve_local_network_cli_uses_framework_backed_module_without_contract_drift(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["solve", "local-network", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == FrameworkDiagnosticEngine(LOCAL_NETWORK_MODULE).solve(_snapshot()).to_json_dict()
    assert payload["command"] == "solve local-network"
    assert [candidate["id"] for candidate in payload["repair_candidates"]] == ["manual-reinstall-chrome", "trace-local-network"]
