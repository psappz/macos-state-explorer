from __future__ import annotations

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.local_network.engine import diagnose_local_network
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus

DESTRUCTIVE_TERMS = (
    "rm ",
    "rm -",
    "kill",
    "killall",
    "pkill",
    "tccutil reset",
    "sqlite3",
    "delete",
    "lsregister -kill",
)


def launchservices_entry(
    *,
    bundle_id: str = "com.google.Chrome",
    name: str = "Google Chrome",
    path: str = "/Applications/Google Chrome.app",
    classification: LaunchServicesStatus = LaunchServicesStatus.ORPHANED,
) -> dict[str, object]:
    return LaunchServicesRecord(
        raw_block="raw",
        bundle_id=bundle_id,
        display_name=name,
        identifier=bundle_id,
        path_clean=path,
        path_exists=False,
        classification=classification,
        node_not_found=classification == LaunchServicesStatus.ORPHANED,
    ).model_dump(mode="python")


def snapshot(
    *,
    entries: list[dict[str, object]] | None = None,
    tcc_stdout: str = "client row",
) -> Snapshot:
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
                payload={"direct_localnetwork_query": {"stdout": tcc_stdout}},
            ),
        ],
    )


def commands_from_diagnosis(diagnosis) -> list[str]:
    commands = list(diagnosis.recommended_next_action.commands)
    commands.append(diagnosis.verification.command)
    for step in diagnosis.fallback_path:
        commands.extend(step.commands)
    return commands


def test_diagnosis_detects_orphaned_chrome_launchservices_records():
    diagnosis = diagnose_local_network(snapshot(entries=[launchservices_entry()]))

    assert "Chrome" in diagnosis.diagnosis
    assert "LaunchServices" in diagnosis.most_likely_cause
    assert diagnosis.confidence >= 0.85
    assert any("Orphaned" in finding.title for finding in diagnosis.evidence)


def test_diagnosis_detects_missing_tcc_localnetwork_rows():
    diagnosis = diagnose_local_network(snapshot(entries=[], tcc_stdout=""))

    assert "TCC" in diagnosis.diagnosis
    assert "Local Network" in diagnosis.most_likely_cause
    assert diagnosis.recommended_next_action.id == "localnetwork.trigger_real_access"


def test_diagnosis_produces_safe_manual_or_read_only_actions_only():
    diagnosis = diagnose_local_network(snapshot(entries=[launchservices_entry()]))
    modes = [diagnosis.recommended_next_action.mode, *(step.mode for step in diagnosis.fallback_path)]

    assert set(modes) <= {"manual", "read-only"}
    assert diagnosis.recommended_next_action.commands == []


def test_diagnosis_includes_verification_command():
    diagnosis = diagnose_local_network(snapshot(entries=[launchservices_entry()]))

    assert diagnosis.verification.command == "mse diagnose local-network"
    assert diagnosis.verification.expected_result


def test_cli_command_mse_diagnose_local_network_works(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))

    result = CliRunner().invoke(app, ["diagnose", "local-network"])

    assert result.exit_code == 0
    assert "Local Network Diagnosis" in result.output
    assert "Verification command" in result.output


def test_no_destructive_command_is_generated():
    diagnosis = diagnose_local_network(snapshot(entries=[launchservices_entry()]))
    commands = [command.lower() for command in commands_from_diagnosis(diagnosis)]

    assert commands
    assert not any(term in command for command in commands for term in DESTRUCTIVE_TERMS)
