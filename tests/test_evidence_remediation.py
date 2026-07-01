from __future__ import annotations

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.remediation.rules import build_remediation_plan


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
    classification: LaunchServicesStatus = LaunchServicesStatus.STALE,
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


def snapshot_with_payloads(*, launchservices: dict[str, object], tcc: dict[str, object] | None = None) -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload=launchservices,
            ),
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload=tcc or {"direct_localnetwork_query": {"stdout": ""}},
            ),
        ],
    )


def test_evidence_generated_from_stale_launchservices_records():
    snapshot = snapshot_with_payloads(
        launchservices={"entries": [launchservices_entry(classification=LaunchServicesStatus.STALE)]}
    )

    evidence = extract_evidence(snapshot)

    ids = {item.id for item in evidence.items}
    assert "launchservices.stale_app_paths" in ids


def test_remediation_generated_from_orphaned_chrome_records():
    snapshot = snapshot_with_payloads(
        launchservices={"entries": [launchservices_entry(classification=LaunchServicesStatus.ORPHANED)]}
    )
    evidence = extract_evidence(snapshot)

    plan = build_remediation_plan(evidence)

    action_ids = {action.id for action in plan.actions}
    assert "chrome.empty_trash_if_present" in action_ids
    assert "chrome.rerun_launchservices" in action_ids
    assert "chrome.rerun_collect" in action_ids


def test_remediation_actions_are_read_only_or_manual_by_default():
    snapshot = snapshot_with_payloads(
        launchservices={"entries": [launchservices_entry(classification=LaunchServicesStatus.ORPHANED)]}
    )
    plan = build_remediation_plan(extract_evidence(snapshot))

    assert plan.actions
    assert {action.mode for action in plan.actions} <= {"manual", "read-only", "unsafe-warning"}
    assert all(action.requires_confirmation or action.mode == "read-only" for action in plan.actions)


def test_no_destructive_command_is_generated():
    snapshot = snapshot_with_payloads(
        launchservices={"entries": [launchservices_entry(classification=LaunchServicesStatus.ORPHANED)]}
    )
    plan = build_remediation_plan(extract_evidence(snapshot))
    commands = [command.lower() for action in plan.actions for command in action.commands]

    assert commands
    assert not any(term in command for command in commands for term in DESTRUCTIVE_TERMS)


def test_tcc_no_localnetwork_rows_generates_evidence_and_remediation():
    snapshot = snapshot_with_payloads(launchservices={"entries": []}, tcc={"direct_localnetwork_query": {"stdout": ""}})

    evidence = extract_evidence(snapshot)
    plan = build_remediation_plan(evidence)

    assert "tcc.no_localnetwork_rows" in {item.id for item in evidence.items}
    assert "localnetwork.trigger_prompt" in {action.id for action in plan.actions}


def test_mse_doctor_still_runs(monkeypatch):
    snapshot = snapshot_with_payloads(
        launchservices={"entries": [launchservices_entry(classification=LaunchServicesStatus.STALE)]}
    )
    snapshot.hypotheses = []
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot)

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Evidence" in result.output
    assert "Hypotheses" in result.output
    assert "Remediation Plan" in result.output
