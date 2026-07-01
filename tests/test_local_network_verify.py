from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.local_network.module import LOCAL_NETWORK_SUPPORTING_COMMANDS
from macos_state_explorer.diagnostics.local_network.verification import verify_local_network
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


def launchservices_entry(
    *,
    bundle_id: str = "com.google.Chrome",
    classification: LaunchServicesStatus = LaunchServicesStatus.ORPHANED,
    path: str = "/Users/test/.Trash/Google Chrome.app",
) -> dict[str, object]:
    return LaunchServicesRecord(
        raw_block="raw",
        bundle_id=bundle_id,
        display_name="Google Chrome",
        identifier=bundle_id,
        path_clean=path,
        path_exists=False,
        classification=classification,
        node_not_found=classification == LaunchServicesStatus.ORPHANED,
    ).model_dump(mode="python")


def snapshot(*, entries: list[dict[str, object]] | None = None) -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={"entries": entries or []},
            ),
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={"direct_localnetwork_query": {"stdout": ""}},
            ),
        ],
    )


def snapshot_without_launchservices() -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={"direct_localnetwork_query": {"stdout": ""}},
            ),
        ],
    )


def trace_ui_correlation() -> dict[str, object]:
    return {"signal_counts": {"securityprivacyextension": 1, "launchservices_csstore": 2, "runningboard": 1}}


def test_verify_success_when_chrome_launchservices_evidence_disappears():
    result = verify_local_network(
        snapshot(entries=[]),
        expected_branch_id="manual-empty-trash-reboot",
    )

    assert result.status == "SUCCESS"
    assert "LaunchServices Chrome/Google stale evidence is absent" in result.expected_change
    assert result.next_repair_candidate is None
    assert result.transition == "workflow-complete"
    assert "No next repair branch is needed" in result.next_step


def test_verify_failed_continues_to_reinstall_branch_when_chrome_evidence_persists():
    result = verify_local_network(
        snapshot(entries=[launchservices_entry()]),
        expected_branch_id="manual-empty-trash-reboot",
    )

    assert result.status == "FAILED"
    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-reinstall-chrome"
    assert result.continues_workflow is True
    assert result.transition == "advance"
    assert "manual-reinstall-chrome" in result.next_step
    assert "retry the same branch only if" in result.retry_guidance.lower()
    assert "If the next branch does not change the diagnosis" in result.fallback_guidance


def test_verify_failed_continues_to_first_ranked_branch_when_expected_branch_is_not_ranked():
    result = verify_local_network(
        snapshot(entries=[launchservices_entry(path="/Volumes/OldDisk/Google Chrome.app")]),
        expected_branch_id="manual-empty-trash-reboot",
    )

    assert result.status == "FAILED"
    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-reinstall-chrome"
    assert result.transition == "fallback-to-current-plan"
    assert "not in the current evidence-ranked plan" in result.observed_result


def test_verify_retries_when_launchservices_evidence_is_incomplete():
    result = verify_local_network(
        snapshot_without_launchservices(),
        expected_branch_id="manual-empty-trash-reboot",
    )

    assert result.status == "RETRY"
    assert result.transition == "retry-current-branch"
    assert result.next_repair_candidate is None
    assert "LaunchServices evidence is incomplete" in result.observed_result
    assert "mse diagnose local-network" in result.retry_guidance
    assert "mse collect" in result.fallback_guidance


def test_verify_unknown_branch_falls_back_to_current_ranked_candidate():
    result = verify_local_network(
        snapshot(entries=[launchservices_entry(path="/Volumes/OldDisk/Google Chrome.app")]),
        expected_branch_id="unknown-branch",
    )

    assert result.status == "FAILED"
    assert result.transition == "fallback-to-current-plan"
    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-reinstall-chrome"
    assert "unknown-branch" in result.observed_result


def test_trace_verification_does_not_loop_to_failed_empty_trash_branch():
    result = verify_local_network(
        snapshot(entries=[launchservices_entry()]),
        expected_branch_id="trace-local-network",
        trace_analysis=trace_ui_correlation(),
        failed_branches={"manual-empty-trash-reboot"},
    )

    assert result.status == "FAILED"
    assert result.transition == "advance"
    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-reinstall-chrome"
    assert result.next_repair_candidate.id != "manual-empty-trash-reboot"
    assert "manual-empty-trash-reboot" in result.observed_result


def test_trace_evidence_after_empty_trash_and_refresh_failures_promotes_non_looping_action():
    result = verify_local_network(
        snapshot(entries=[launchservices_entry()]),
        expected_branch_id="trace-local-network",
        trace_analysis=trace_ui_correlation(),
        failed_branches={"manual-empty-trash-reboot", "refresh-launchservices-user-cache"},
    )

    assert result.status == "FAILED"
    assert {"LN-E004", "LN-E005", "LN-E009"}.issubset(set(result.evidence_ids))
    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-reinstall-chrome"
    assert "manual-reinstall-chrome" in result.next_step


def test_trace_verification_standalone_without_history_preserves_current_ranked_plan():
    result = verify_local_network(
        snapshot(entries=[launchservices_entry()]),
        expected_branch_id="trace-local-network",
        trace_analysis=trace_ui_correlation(),
    )

    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-empty-trash-reboot"


def test_verify_retry_guidance_uses_positional_trace_output_path():
    result = verify_local_network(snapshot(entries=[]), expected_branch_id="trace-local-network")

    assert "mse trace local-network ~/Desktop/mse-local-network-trace" in result.retry_guidance
    assert "--out" not in result.retry_guidance


def test_supporting_command_text_uses_actual_trace_syntax():
    trace_commands = [command for command in LOCAL_NETWORK_SUPPORTING_COMMANDS if command.startswith("mse trace local-network")]

    assert trace_commands == ["mse trace local-network ~/Desktop/mse-local-network-trace"]
    assert all("--out" not in command for command in LOCAL_NETWORK_SUPPORTING_COMMANDS)


def test_verify_local_network_cli_outputs_status_and_next_branch(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))

    result = CliRunner().invoke(app, ["verify", "local-network", "--branch", "manual-empty-trash-reboot"])

    assert result.exit_code == 0
    assert "Verification: FAILED" in result.output
    assert "Transition: advance" in result.output
    assert "Next step:" in result.output
    assert "Retry guidance:" in result.output
    assert "Fallback guidance:" in result.output
    assert "Next repair candidate" in result.output
    assert "manual-reinstall-chrome" in result.output


def test_verify_cli_audit_history_prevents_trace_loop(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))
    monkeypatch.setattr("macos_state_explorer.cli.load_trace_analysis", lambda trace: trace_ui_correlation())
    audit_log = tmp_path / "repair-audit.jsonl"
    audit_log.write_text(
        json.dumps(
            {
                "result": {
                    "step_results": [
                        {
                            "candidate_id": "manual-empty-trash-reboot",
                            "action_id": None,
                            "verification": {"status": "FAILED"},
                        }
                    ]
                }
            }
        )
        + "\n"
    )

    result = CliRunner().invoke(
        app,
        [
            "verify",
            "local-network",
            "--branch",
            "trace-local-network",
            "--trace",
            str(tmp_path / "trace"),
            "--audit-log",
            str(audit_log),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["next_repair_candidate"]["id"] == "manual-reinstall-chrome"
    assert "manual-empty-trash-reboot" in payload["observed_result"]


def test_verify_cli_failed_branch_excludes_manual_empty_trash_after_trace(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))
    monkeypatch.setattr("macos_state_explorer.cli.load_trace_analysis", lambda trace: trace_ui_correlation())

    result = CliRunner().invoke(
        app,
        [
            "verify",
            "local-network",
            "--branch",
            "trace-local-network",
            "--trace",
            str(tmp_path / "trace"),
            "--failed-branch",
            "manual-empty-trash-reboot",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["next_repair_candidate"]["id"] == "manual-reinstall-chrome"
    assert "manual-empty-trash-reboot" in payload["observed_result"]


def test_verify_cli_repeated_failed_branch_reports_no_safe_repair(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))
    monkeypatch.setattr("macos_state_explorer.cli.load_trace_analysis", lambda trace: trace_ui_correlation())

    result = CliRunner().invoke(
        app,
        [
            "verify",
            "local-network",
            "--branch",
            "trace-local-network",
            "--trace",
            str(tmp_path / "trace"),
            "--failed-branch",
            "manual-empty-trash-reboot",
            "--failed-branch",
            "manual-reinstall-chrome",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["next_repair_candidate"] is None
    assert "no safe automatic repair remains" in payload["next_action"]["step"]
    assert "support bundle" in payload["fallback_guidance"]


def test_audit_candidate_id_extraction_excludes_failed_manual_only_branch(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))
    monkeypatch.setattr("macos_state_explorer.cli.load_trace_analysis", lambda trace: trace_ui_correlation())
    audit_log = tmp_path / "repair-audit.jsonl"
    audit_log.write_text(
        json.dumps(
            {
                "result": {
                    "step_results": [
                        {
                            "candidate_id": "manual-empty-trash-reboot",
                            "action_id": None,
                            "status": "FAILED",
                            "verification": {"status": "FAILED"},
                        }
                    ]
                }
            }
        )
        + "\n"
    )

    result = CliRunner().invoke(
        app,
        [
            "verify",
            "local-network",
            "--branch",
            "trace-local-network",
            "--trace",
            str(tmp_path / "trace"),
            "--audit-log",
            str(audit_log),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["next_repair_candidate"]["id"] == "manual-reinstall-chrome"
    assert "manual-empty-trash-reboot" in payload["observed_result"]


def test_action_id_only_audit_failure_does_not_pollute_failed_branch_wording(monkeypatch, tmp_path):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))
    monkeypatch.setattr("macos_state_explorer.cli.load_trace_analysis", lambda trace: trace_ui_correlation())
    audit_log = tmp_path / "repair-audit.jsonl"
    audit_log.write_text(
        json.dumps(
            {
                "result": {
                    "step_results": [
                        {
                            "candidate_id": None,
                            "action_id": "refresh-launchservices-user-cache",
                            "status": "FAILED",
                            "repair_result": {"status": "FAILED", "action_id": "refresh-launchservices-user-cache"},
                        }
                    ]
                }
            }
        )
        + "\n"
    )

    result = CliRunner().invoke(
        app,
        [
            "verify",
            "local-network",
            "--branch",
            "trace-local-network",
            "--trace",
            str(tmp_path / "trace"),
            "--audit-log",
            str(audit_log),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "refresh-launchservices-user-cache" not in payload["observed_result"]
    assert "Previously failed workflow branches" not in payload["observed_result"]


def test_verify_local_network_cli_success_has_no_next_branch(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[]))

    result = CliRunner().invoke(app, ["verify", "local-network", "--branch", "manual-empty-trash-reboot"])

    assert result.exit_code == 0
    assert "Verification: SUCCESS" in result.output
    assert "Next repair candidate" not in result.output
