from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.local_network.module import LOCAL_NETWORK_MODULE
from macos_state_explorer.solver.local_network import build_local_network_solution


def _snapshot() -> Snapshot:
    return Snapshot(
        host="local-network-repair-host",
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
                        {"bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app", "classification": "STALE"}
                    ],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices.csstore\n"},
                },
            ),
        ],
    )


def test_local_network_candidates_can_expose_optional_repair_actions_without_json_contract_drift():
    solution = build_local_network_solution(_snapshot())

    candidate_by_id = {candidate.id: candidate for candidate in solution.repair_plan}
    assert candidate_by_id["manual-reinstall-chrome"].action_id == "refresh-launchservices-user-cache"
    assert candidate_by_id["trace-local-network"].action_id == "open-local-network-settings"

    payload = solution.to_json_dict()
    assert list(payload["repair_candidates"][0]) == [
        "id",
        "title",
        "risk",
        "manual_action",
        "expected_result",
        "verification_command",
        "fallback_branch",
        "evidence_ids",
    ]
    assert "action_id" not in payload["repair_candidates"][0]


def test_repair_local_network_dry_run_json_uses_ranked_repair_action(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--dry-run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload) == [
        "command",
        "module",
        "action_id",
        "candidate_id",
        "status",
        "dry_run",
        "safety_classification",
        "why_safe",
        "preconditions",
        "rollback",
        "executed_commands",
        "message",
        "files_touched",
        "errors",
        "audit_log",
    ]
    assert payload["command"] == "repair local-network"
    assert payload["action_id"] == "refresh-launchservices-user-cache"
    assert payload["candidate_id"] == "manual-reinstall-chrome"
    assert payload["status"] == "DRY_RUN"
    assert payload["dry_run"] is True
    assert payload["safety_classification"] in {"low", "moderate"}
    assert "derived" in payload["why_safe"] or "user-domain" in payload["why_safe"]
    assert payload["executed_commands"][0]["exit_code"] is None


def test_repair_local_network_human_dry_run_displays_safety_reason(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--dry-run"])

    assert result.exit_code == 0
    assert "Repair action" in result.stdout
    assert "Status: DRY_RUN" in result.stdout
    assert "Why safe" in result.stdout
    assert "refresh-launchservices-user-cache" in result.stdout


def test_local_network_repair_execution_uses_injected_runner_for_idempotency(monkeypatch):
    executed: list[list[str]] = []

    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 0, "ok", ""

    actions = LOCAL_NETWORK_MODULE.repair_actions([], {}, {"command_runner": fake_runner})
    first = actions["refresh-launchservices-user-cache"].run(dry_run=False)
    second = actions["refresh-launchservices-user-cache"].run(dry_run=False)

    assert first.status.name == "SUCCESS"
    assert second.status.name == "SUCCESS"
    assert executed == [
        ["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister", "-kill", "-r", "-domain", "user"],
        ["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister", "-kill", "-r", "-domain", "user"],
    ]


def test_repair_local_network_execute_requires_confirm_and_writes_audit_log(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    audit_log = tmp_path / "repair-audit.jsonl"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["repair", "local-network", "--execute", "--json", "--audit-log", str(audit_log)],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["dry_run"] is False
    assert payload["audit_log"] == str(audit_log)
    event = json.loads(audit_log.read_text().splitlines()[0])
    assert event["module"] == "local-network"
    assert event["mode"] == "execute"
    assert event["result"]["status"] == "BLOCKED"
    assert "confirmation" in event["errors"][0].lower()


def test_repair_local_network_confirmed_execution_json_records_audit_log(monkeypatch, tmp_path):
    executed: list[list[str]] = []

    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 0, "opened", ""

    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    monkeypatch.setattr("macos_state_explorer.diagnostics.framework.default_command_runner", fake_runner)
    audit_log = tmp_path / "repair-audit.jsonl"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "repair",
            "local-network",
            "--action",
            "open-local-network-settings",
            "--execute",
            "--confirm",
            "--json",
            "--audit-log",
            str(audit_log),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "SUCCESS"
    assert payload["dry_run"] is False
    assert payload["audit_log"] == str(audit_log)
    assert executed == [["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"]]
    event = json.loads(audit_log.read_text().splitlines()[0])
    assert event["selected_action"] == {"id": "open-local-network-settings", "candidate_id": "trace-local-network"}
    assert event["result"]["status"] == "SUCCESS"
    assert event["rollback"]["available"] is True


def test_repair_local_network_dry_run_with_audit_log_does_not_execute(monkeypatch, tmp_path):
    executed: list[list[str]] = []

    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 0, "unexpected", ""

    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    monkeypatch.setattr("macos_state_explorer.diagnostics.framework.default_command_runner", fake_runner)
    audit_log = tmp_path / "repair-audit.jsonl"
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--dry-run", "--audit-log", str(audit_log), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "DRY_RUN"
    assert executed == []
    event = json.loads(audit_log.read_text().splitlines()[0])
    assert event["mode"] == "dry-run"
    assert event["files_touched"]


def test_solve_and_report_json_contracts_remain_unchanged_after_repair_audit(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    solve = runner.invoke(app, ["solve", "local-network", "--json"])
    report = runner.invoke(app, ["report", "local-network", "--json"])

    assert solve.exit_code == 0
    assert list(json.loads(solve.stdout)) == ["command", "diagnosis", "evidence", "matched_rules", "repair_candidates", "next_action"]
    assert report.exit_code == 0
    assert list(json.loads(report.stdout)) == [
        "command",
        "system_context",
        "trace",
        "diagnosis",
        "evidence",
        "matched_rules",
        "repair_candidates",
        "verification",
        "next_actions",
    ]


def test_repair_local_network_unknown_action_fails_cleanly(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--action", "missing", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "NOT_FOUND"
    assert payload["action_id"] == "missing"
