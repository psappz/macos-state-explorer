from __future__ import annotations

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.local_network.verification import verify_local_network
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


def launchservices_entry(
    *,
    bundle_id: str = "com.google.Chrome",
    classification: LaunchServicesStatus = LaunchServicesStatus.ORPHANED,
) -> dict[str, object]:
    return LaunchServicesRecord(
        raw_block="raw",
        bundle_id=bundle_id,
        display_name="Google Chrome",
        identifier=bundle_id,
        path_clean="/Users/test/.Trash/Google Chrome.app",
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


def test_verify_success_when_chrome_launchservices_evidence_disappears():
    result = verify_local_network(
        snapshot(entries=[]),
        expected_branch_id="manual-empty-trash-reboot",
    )

    assert result.status == "SUCCESS"
    assert "LaunchServices Chrome/Google stale evidence is absent" in result.expected_change
    assert result.next_repair_candidate is None


def test_verify_failed_continues_to_reinstall_branch_when_chrome_evidence_persists():
    result = verify_local_network(
        snapshot(entries=[launchservices_entry()]),
        expected_branch_id="manual-empty-trash-reboot",
    )

    assert result.status == "FAILED"
    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-reinstall-chrome"
    assert result.continues_workflow is True


def test_verify_local_network_cli_outputs_status_and_next_branch(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[launchservices_entry()]))

    result = CliRunner().invoke(app, ["verify", "local-network", "--branch", "manual-empty-trash-reboot"])

    assert result.exit_code == 0
    assert "Verification: FAILED" in result.output
    assert "Next repair candidate" in result.output
    assert "manual-reinstall-chrome" in result.output


def test_verify_local_network_cli_success_has_no_next_branch(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast: snapshot(entries=[]))

    result = CliRunner().invoke(app, ["verify", "local-network", "--branch", "manual-empty-trash-reboot"])

    assert result.exit_code == 0
    assert "Verification: SUCCESS" in result.output
    assert "Next repair candidate" not in result.output
