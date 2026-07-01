from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.reports.bundle_diff import compare_support_bundles

DIFF_REQUIRED_KEYS = [
    "command",
    "schema_version",
    "before",
    "after",
    "summary",
    "diagnoses",
    "evidence",
]


def test_bundle_diff_reports_resolved_diagnosis_and_removed_evidence(tmp_path):
    before = _write_bundle(
        tmp_path / "before",
        _report(
            diagnosis="Chrome Local Network prompt is blocked by stale LaunchServices identity evidence.",
            rule_ids=["ln-rule-chrome-identity-reinstall"],
            evidence=[("LN-E001", True), ("LN-E006", True), ("LN-E009", False)],
        ),
    )
    after = _write_bundle(
        tmp_path / "after",
        _report(
            diagnosis="No Local Network evidence was found.",
            rule_ids=[],
            evidence=[("LN-E001", False), ("LN-E006", False), ("LN-E009", False)],
        ),
    )

    result = compare_support_bundles(before, after).to_json_dict()

    _assert_required_key_prefix(result, DIFF_REQUIRED_KEYS)
    assert result["summary"] == {
        "status": "improved",
        "resolved_diagnosis_count": 1,
        "remaining_diagnosis_count": 0,
        "new_diagnosis_count": 0,
        "removed_evidence_count": 2,
        "remaining_evidence_count": 0,
        "new_evidence_count": 0,
    }
    assert [item["id"] for item in result["diagnoses"]["resolved"]] == ["ln-rule-chrome-identity-reinstall"]
    assert result["diagnoses"]["remaining"] == []
    assert result["diagnoses"]["new"] == []
    assert [item["id"] for item in result["evidence"]["removed"]] == ["LN-E001", "LN-E006"]
    assert result["evidence"]["remaining"] == []
    assert result["evidence"]["new"] == []


def test_bundle_diff_reports_unchanged_remaining_diagnosis_and_evidence(tmp_path):
    before = _write_bundle(
        tmp_path / "before",
        _report(rule_ids=["ln-rule-tcc-missing"], evidence=[("LN-E001", True), ("LN-E002", False)]),
    )
    after = _write_bundle(
        tmp_path / "after",
        _report(rule_ids=["ln-rule-tcc-missing"], evidence=[("LN-E001", True), ("LN-E002", False)]),
    )

    result = compare_support_bundles(before, after).to_json_dict()

    assert result["summary"]["status"] == "unchanged"
    assert [item["id"] for item in result["diagnoses"]["remaining"]] == ["ln-rule-tcc-missing"]
    assert [item["id"] for item in result["evidence"]["remaining"]] == ["LN-E001"]


def test_bundle_diff_reports_partial_resolution_and_regression_deterministically(tmp_path):
    before = _write_bundle(
        tmp_path / "before",
        _report(
            rule_ids=["ln-rule-chrome-identity-reinstall", "ln-rule-tcc-missing"],
            evidence=[("LN-E006", True), ("LN-E001", True), ("LN-E003", True)],
        ),
    )
    after = _write_bundle(
        tmp_path / "after",
        _report(
            rule_ids=["ln-rule-tcc-missing", "ln-rule-new-regression"],
            evidence=[("LN-E003", True), ("LN-E001", True), ("LN-E008", True)],
        ),
    )

    result = compare_support_bundles(before, after).to_json_dict()

    assert result["summary"]["status"] == "mixed"
    assert [item["id"] for item in result["diagnoses"]["resolved"]] == ["ln-rule-chrome-identity-reinstall"]
    assert [item["id"] for item in result["diagnoses"]["remaining"]] == ["ln-rule-tcc-missing"]
    assert [item["id"] for item in result["diagnoses"]["new"]] == ["ln-rule-new-regression"]
    assert [item["id"] for item in result["evidence"]["removed"]] == ["LN-E006"]
    assert [item["id"] for item in result["evidence"]["remaining"]] == ["LN-E001", "LN-E003"]
    assert [item["id"] for item in result["evidence"]["new"]] == ["LN-E008"]


def test_bundle_diff_reports_no_evidence_case(tmp_path):
    before = _write_bundle(tmp_path / "before", _report(rule_ids=[], evidence=[("LN-E001", False)]))
    after = _write_bundle(tmp_path / "after", _report(rule_ids=[], evidence=[("LN-E001", False)]))

    result = compare_support_bundles(before, after).to_json_dict()

    assert result["summary"]["status"] == "unchanged"
    assert result["diagnoses"] == {"resolved": [], "remaining": [], "new": []}
    assert result["evidence"] == {"removed": [], "remaining": [], "new": []}


def test_bundle_diff_cli_json_and_human_output(tmp_path):
    before = _write_bundle(tmp_path / "before", _report(rule_ids=["ln-rule-tcc-missing"], evidence=[("LN-E001", True)]))
    after = _write_bundle(tmp_path / "after", _report(rule_ids=[], evidence=[("LN-E001", False)]))
    runner = CliRunner()

    json_result = runner.invoke(app, ["diff", "bundles", str(before), str(after), "--json"])
    text_result = runner.invoke(app, ["diff", "bundles", str(before), str(after)])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    _assert_required_key_prefix(payload, DIFF_REQUIRED_KEYS)
    assert payload["summary"]["status"] == "improved"
    assert text_result.exit_code == 0
    assert text_result.stdout.startswith("Bundle comparison")
    assert "Resolved diagnoses" in text_result.stdout
    assert "ln-rule-tcc-missing" in text_result.stdout


def test_bundle_diff_rejects_missing_report_json(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code != 0
    assert "Missing report.json" in result.stdout


def _write_bundle(path, report):
    path.mkdir()
    (path / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return path


def _report(*, rule_ids, evidence, diagnosis="Synthetic Local Network diagnosis"):
    return {
        "command": "report local-network",
        "system_context": {"host": "test-host", "snapshot_created_at": 123.0},
        "diagnosis": diagnosis,
        "evidence": [
            {
                "id": evidence_id,
                "title": f"Evidence {evidence_id}",
                "detail": f"Detail for {evidence_id}",
                "source": "test",
                "present": present,
                "confidence": 0.8,
                "provenance": [],
            }
            for evidence_id, present in evidence
        ],
        "matched_rules": [
            {
                "id": rule_id,
                "diagnosis_id": rule_id.replace("ln-rule-", "ln-diagnosis-"),
                "explanation": f"Explanation for {rule_id}",
                "repair_recommendations": [],
            }
            for rule_id in rule_ids
        ],
        "repair_candidates": [],
        "verification": {"status": "FAILED", "evidence_ids": [item[0] for item in evidence if item[1]]},
        "next_actions": [],
    }


def _assert_required_key_prefix(payload: dict[str, object], required_keys: list[str]) -> None:
    assert list(payload)[: len(required_keys)] == required_keys
