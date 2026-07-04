from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot


def _snapshot() -> Snapshot:
    return Snapshot(
        host="test-host",
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
                        {
                            "bundle_id": "com.google.Chrome",
                            "path": "/Applications/Google Chrome.app",
                            "classification": "STALE",
                        }
                    ],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices.csstore\n"},
                },
            ),
        ],
    )


def test_solve_local_network_json_schema_and_order(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["solve", "local-network", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload)[:6] == ["command", "diagnosis", "evidence", "matched_rules", "repair_candidates", "next_action"]
    assert "remediation_plan_summary" in payload
    assert payload["command"] == "solve local-network"
    assert [item["id"] for item in payload["evidence"]] == [
        "LN-E001",
        "LN-E002",
        "LN-E003",
        "LN-E004",
        "LN-E005",
        "LN-E006",
        "LN-E007",
        "LN-E008",
        "LN-E009",
    ]
    assert list(payload["evidence"][0]) == ["id", "title", "detail", "source", "present", "confidence", "provenance"]
    assert payload["matched_rules"][0]["id"] == "ln-rule-chrome-identity-reinstall"
    assert list(payload["matched_rules"][0]) == [
        "id",
        "diagnosis_id",
        "matched_required_evidence",
        "matched_optional_evidence",
        "matched_conflicting_evidence",
        "confidence_contribution",
        "repair_recommendations",
        "explanation",
    ]
    assert payload["repair_candidates"][0]["id"] == "manual-reinstall-chrome"
    assert payload["next_action"]["id"] == payload["repair_candidates"][0]["id"]


def test_verify_local_network_json_schema_and_next_action(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["verify", "local-network", "--branch", "manual-reinstall-chrome", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload) == [
        "command",
        "status",
        "branch_id",
        "transition",
        "expected_change",
        "observed_result",
        "current_diagnosis",
        "evidence_ids",
        "continues_workflow",
        "next_repair_candidate",
        "next_action",
        "retry_guidance",
        "fallback_guidance",
    ]
    assert payload["command"] == "verify local-network"
    assert payload["status"] == "FAILED"
    assert payload["next_action"]["type"] in {"advance", "fallback-to-current-plan", "retry-current-branch", "workflow-complete"}
    if payload["next_repair_candidate"]:
        assert list(payload["next_repair_candidate"]) == [
            "id",
            "title",
            "risk",
            "manual_action",
            "expected_result",
            "verification_command",
            "fallback_branch",
            "evidence_ids",
        ]


def test_trace_local_network_json_schema_and_order(monkeypatch, tmp_path):
    analysis = {
        "created_at": 1.0,
        "keyword_hits": {"Chrome": 2},
        "signal_counts": {"chrome_code_sign_clone": 1},
        "correlation_summary": [
            {
                "signal": "chrome_code_sign_clone",
                "count": 1,
                "sources": ["log_stream.txt"],
                "description": "Chrome code-sign clone identity observed",
            }
        ],
        "timeline_events": [
            {
                "timestamp": "2026-07-01 12:00:00",
                "source_file": "log_stream.txt",
                "signal": "chrome_code_sign_clone",
                "description": "Chrome code-sign clone identity observed",
                "process": "lsd",
                "paths": [],
                "line": "lsd com.google.Chrome.code_sign_clone",
            }
        ],
        "candidate_paths": [],
    }

    def fake_trace(out, seconds=None):
        return analysis

    monkeypatch.setattr("macos_state_explorer.cli.trace_local_network", fake_trace)
    runner = CliRunner()

    result = runner.invoke(app, ["trace", "local-network", str(tmp_path), "--seconds", "0", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload) == [
        "command",
        "out",
        "analysis",
        "signals",
        "candidate_paths",
        "next_action",
    ]
    assert list(payload["analysis"]) == [
        "created_at",
        "keyword_hits",
        "signal_counts",
        "correlation_summary",
        "timeline_events",
        "normalized_events",
        "trace_timeline_summary",
    ]
    assert payload["signals"][0]["signal"] == "chrome_code_sign_clone"
    assert payload["next_action"] == {
        "type": "inspect-solve",
        "command": f"mse solve local-network --trace {tmp_path}",
    }
