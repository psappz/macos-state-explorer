from __future__ import annotations

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.solver.local_network import build_local_network_solution


def _snapshot_with_known_evidence() -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={
                    "direct_localnetwork_query": {"stdout": ""},
                    "user_tcc": {"hits": []},
                    "system_tcc": {"hits": []},
                    "regdb": {"hits": []},
                },
            ),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "stale_entries": [
                        {"bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app"},
                        {"bundle_id": "com.google.Chrome.code_sign_clone", "path": "/Users/test/.Trash/Google Chrome.app"},
                    ],
                    "candidate_files": {"stdout": "/private/var/db/com.apple.xpc.launchd/disabled.plist\n"},
                },
            ),
        ],
    )


def test_solver_proposes_empty_trash_reboot_reinstall_trace_in_order():
    solution = build_local_network_solution(_snapshot_with_known_evidence())

    assert [candidate.id for candidate in solution.repair_plan] == [
        "manual-empty-trash-reboot",
        "manual-reinstall-chrome",
        "trace-local-network",
    ]


def test_solver_never_emits_destructive_commands():
    solution = build_local_network_solution(_snapshot_with_known_evidence())
    text = solution.render_text()

    forbidden = [
        "rm ",
        "rm -rf",
        "killall",
        "pkill",
        "tccutil reset",
        "DELETE FROM",
        "UPDATE ",
        "INSERT INTO",
        "sqlite3 ",
    ]
    assert not any(token in text for token in forbidden)
    assert "Manual only" in text


def test_solver_uses_evidence_ids():
    solution = build_local_network_solution(_snapshot_with_known_evidence())

    evidence_ids = {e.id for e in solution.evidence}
    assert evidence_ids
    for candidate in solution.repair_plan:
        assert candidate.evidence_ids
        assert set(candidate.evidence_ids).issubset(evidence_ids)
    assert "Evidence:" in solution.render_text()


def test_cli_solve_local_network_command_works(monkeypatch):
    monkeypatch.setattr(
        "macos_state_explorer.cli.create_snapshot",
        lambda fast=False: _snapshot_with_known_evidence(),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["solve", "local-network"])

    assert result.exit_code == 0
    assert "Current diagnosis" in result.stdout
    assert "Repair candidate" in result.stdout
    assert "Risk" in result.stdout
    assert "Expected result" in result.stdout
    assert "Verification command" in result.stdout
    assert "Fallback branch" in result.stdout
