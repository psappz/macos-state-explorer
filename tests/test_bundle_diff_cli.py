from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app


def write_bundle(path, *, evidence, diagnosis="diagnosis", branch="manual-empty-trash-reboot", generation_diff=None, launchservices_fix_ready_runbook=None):
    path.mkdir(parents=True)
    (path / "report.json").write_text(
        json.dumps(
            {
                "command": "report local-network",
                "diagnosis": diagnosis,
                "evidence": evidence,
                "repair_candidates": [{"id": branch, "title": "Manual branch", "evidence_ids": [item["id"] for item in evidence if item.get("present")]}],
                "verification": {"status": "FAILED", "branch_id": branch},
                "remediation_plan_summary": {"step_count": len(evidence)},
                "generation_diff": generation_diff or {"removed": [], "added": [], "persisted": [], "regenerated": []},
                "launchservices_fix_ready_runbook": launchservices_fix_ready_runbook
                or {
                    "available": False,
                    "next_real_world_fix_attempt": None,
                    "verification_command": None,
                    "do_not_continue_networkextension": False,
                },
            },
            indent=2,
        )
        + "\n"
    )
    (path / "command.json").write_text(json.dumps({"command": "mse report local-network --bundle", "bundle_schema_version": 1}) + "\n")



def test_diff_bundles_cli_registered_and_renders_human_output(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_bundle(before, evidence=[{"id": "stale-launchservices", "present": True}, {"id": "trace-only", "present": True}])
    write_bundle(after, evidence=[{"id": "trace-only", "present": True}, {"id": "new-signal", "present": True}], diagnosis="changed")

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)])

    assert result.exit_code == 0
    assert "Support bundle diff" in result.stdout
    assert "Removed evidence" in result.stdout
    assert "stale-launchservices" in result.stdout
    assert "Added evidence" in result.stdout
    assert "new-signal" in result.stdout
    assert "Changed fields" in result.stdout
    assert "diagnosis" in result.stdout


def test_diff_bundles_cli_registered_and_renders_json_output(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_bundle(before, evidence=[{"id": "stale-launchservices", "present": True}])
    write_bundle(after, evidence=[])

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "diff bundles"
    assert payload["before"]["path"] == str(before)
    assert payload["after"]["path"] == str(after)
    assert payload["evidence_diff"]["removed"] == ["stale-launchservices"]
    assert payload["evidence_diff"]["added"] == []
    assert "report.json" in payload["files"]["common"]


def test_diff_bundles_includes_generation_diff_json(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_bundle(before, evidence=[], generation_diff={"removed": [], "added": [], "persisted": ["chrome-old"], "regenerated": []})
    write_bundle(after, evidence=[], generation_diff={"removed": ["chrome-old"], "added": ["chrome-new"], "persisted": ["chrome-active"], "regenerated": ["chrome-old"]})

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["generation_diff"] == {
        "removed": ["chrome-old"],
        "added": ["chrome-new"],
        "persisted": ["chrome-active"],
        "regenerated": ["chrome-old"],
    }


def test_diff_bundles_renders_generation_diff_human_output(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_bundle(before, evidence=[])
    write_bundle(after, evidence=[], generation_diff={"removed": ["chrome-old"], "added": [], "persisted": ["chrome-active"], "regenerated": ["chrome-old"]})

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)])

    assert result.exit_code == 0
    assert "Generation diff" in result.stdout
    assert "Removed generations: chrome-old" in result.stdout
    assert "Persisted generations: chrome-active" in result.stdout
    assert "Regenerated generations: chrome-old" in result.stdout


def test_diff_bundles_reports_launchservices_fix_ready_runbook_transition(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_bundle(before, evidence=[])
    write_bundle(
        after,
        evidence=[],
        launchservices_fix_ready_runbook={
            "available": True,
            "next_real_world_fix_attempt": "manual_empty_trash_reboot",
            "verification_command": "mse verify local-network --branch manual-empty-trash-reboot",
            "do_not_continue_networkextension": True,
        },
    )

    json_result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    text_result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after)])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["launchservices_fix_ready_runbook_diff"] == {
        "available_before": False,
        "available_after": True,
        "next_real_world_fix_attempt_before": None,
        "next_real_world_fix_attempt_after": "manual_empty_trash_reboot",
        "verification_command_before": None,
        "verification_command_after": "mse verify local-network --branch manual-empty-trash-reboot",
        "do_not_continue_networkextension_before": False,
        "do_not_continue_networkextension_after": True,
    }
    assert text_result.exit_code == 0
    assert "LaunchServices Fix-Ready Runbook Diff" in text_result.stdout
    assert "Availability: False → True" in text_result.stdout
    assert "Next real-world fix attempt: none → manual_empty_trash_reboot" in text_result.stdout
    assert "Verification command: none → mse verify local-network --branch manual-empty-trash-reboot" in text_result.stdout
    assert "Do not continue NetworkExtension: False → True" in text_result.stdout
