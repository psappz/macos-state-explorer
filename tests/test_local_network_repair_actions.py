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


def _clean_snapshot() -> Snapshot:
    return Snapshot(
        host="local-network-repair-host-clean",
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
                    "stale_entries": [],
                    "entries": [],
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


def test_repair_local_network_dry_run_json_uses_ranked_repair_plan(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload) == [
        "command",
        "module",
        "status",
        "dry_run",
        "confirmed",
        "plan",
        "step_results",
        "message",
        "audit_log",
    ]
    assert payload["command"] == "repair local-network"
    assert payload["status"] == "DRY_RUN"
    assert payload["dry_run"] is True
    assert [step["candidate_id"] for step in payload["plan"]["steps"]] == [
        "manual-reinstall-chrome",
        "trace-local-network",
    ]
    assert payload["plan"]["steps"][0]["action_id"] == "refresh-launchservices-user-cache"
    assert payload["step_results"][0]["status"] == "DRY_RUN"
    assert payload["step_results"][0]["repair_result"]["executed_commands"][0]["exit_code"] is None


def test_repair_local_network_confirm_executes_plan_and_verifies(monkeypatch):
    executed: list[list[str]] = []
    snapshots = iter([_snapshot(), _clean_snapshot()])

    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 0, "ok", ""

    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: next(snapshots))
    monkeypatch.setattr("macos_state_explorer.diagnostics.framework.default_command_runner", fake_runner)
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--confirm", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "SUCCESS"
    assert payload["dry_run"] is False
    assert payload["confirmed"] is True
    assert executed == [
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
            "-r",
            "-f",
            "-apps",
            "user",
        ],
    ]
    executed_step = next(step for step in payload["step_results"] if step["repair_result"])
    assert executed_step["repair_result"]["status"] != "DRY_RUN"
    assert executed_step["repair_result"]["dry_run"] is False
    assert executed_step["verification"]["status"] == "SUCCESS"


def test_repair_local_network_confirmed_execution_never_reports_dry_run_status(monkeypatch):
    executed: list[list[str]] = []
    snapshots = iter([_snapshot(), _clean_snapshot()])

    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 0, "ok", ""

    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: next(snapshots))
    monkeypatch.setattr("macos_state_explorer.diagnostics.framework.default_command_runner", fake_runner)
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--confirm", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    executed_results = [step["repair_result"] for step in payload["step_results"] if step["repair_result"]]
    assert executed_results
    assert all(repair_result["status"] != "DRY_RUN" for repair_result in executed_results)


def test_refresh_launchservices_default_action_never_uses_removed_kill_option(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    argv = payload["step_results"][0]["repair_result"]["executed_commands"][0]["argv"]
    assert "-kill" not in argv
    assert argv == [
        "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
        "-r",
        "-f",
        "-apps",
        "user",
    ]


def test_refresh_launchservices_preflight_uncertainty_does_not_block_safe_execution():
    executed: list[list[str]] = []

    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        assert command[-1] != "-h"
        return 0, "refreshed", ""

    actions = LOCAL_NETWORK_MODULE.repair_actions([], {}, {"command_runner": fake_runner})
    result = actions["refresh-launchservices-user-cache"].run(dry_run=False)

    assert result.status.name == "SUCCESS"
    assert executed == [
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
            "-r",
            "-f",
            "-apps",
            "user",
        ]
    ]


def test_refresh_launchservices_unsupported_command_failure_reports_stderr_and_guidance():
    executed: list[list[str]] = []

    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 64, "", "lsregister: unknown option -- apps"

    actions = LOCAL_NETWORK_MODULE.repair_actions([], {}, {"command_runner": fake_runner})
    result = actions["refresh-launchservices-user-cache"].run(dry_run=False)

    assert result.status.name == "FAILED"
    assert executed == [
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
            "-r",
            "-f",
            "-apps",
            "user",
        ]
    ]
    assert "does not support one of the requested options" in result.message
    assert "manual reinstall or trace fallback" in result.message
    assert result.errors == ("lsregister: unknown option -- apps",)


def test_repair_local_network_explicit_action_preserves_single_action_json(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["repair", "local-network", "--action", "refresh-launchservices-user-cache", "--dry-run", "--json"],
    )

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
    assert payload["action_id"] == "refresh-launchservices-user-cache"
    assert payload["candidate_id"] == "manual-reinstall-chrome"
    assert payload["status"] == "DRY_RUN"


def test_repair_local_network_human_dry_run_displays_safety_reason(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["repair", "local-network", "--dry-run"])

    assert result.exit_code == 0
    assert "Repair plan" in result.stdout
    assert "Status: DRY_RUN" in result.stdout
    assert "manual-reinstall-chrome" in result.stdout
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
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
            "-r",
            "-f",
            "-apps",
            "user",
        ],
        [
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
            "-r",
            "-f",
            "-apps",
            "user",
        ],
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
    assert event["mode"] == "execute-plan"
    assert event["result"]["status"] == "BLOCKED"
    assert "confirm" in event["result"]["message"].lower()


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
    assert event["mode"] == "dry-run-plan"
    assert event["result"]["step_results"][0]["repair_result"]["files_touched"]


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
