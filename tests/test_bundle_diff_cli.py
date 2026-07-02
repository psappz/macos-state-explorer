from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app


def write_bundle(path, *, evidence, diagnosis="diagnosis", branch="manual-empty-trash-reboot", generation_diff=None):
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
