from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot

DOC_PATH = Path("docs/LOCAL_NETWORK_JSON_CONTRACTS.md")
EXAMPLE_DIR = Path("docs/examples/local-network-json")

SOLVE_REQUIRED_KEYS = ["command", "diagnosis", "evidence", "matched_rules", "repair_candidates", "next_action"]
VERIFY_REQUIRED_KEYS = [
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
TRACE_REQUIRED_KEYS = ["command", "out", "analysis", "signals", "candidate_paths", "next_action"]


def _empty_snapshot() -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={"direct_localnetwork_query": {"stdout": "kTCCServiceLocalNetwork|com.apple.Terminal"}},
            ),
            Observation(collector="launchservices", started_at=1, ended_at=2, payload={"stale_entries": []}),
        ],
    )


def test_json_contract_doc_exists_and_links_all_examples():
    text = DOC_PATH.read_text()

    assert "# Local Network JSON contracts" in text
    for command in ("mse solve local-network --json", "mse verify local-network --json", "mse trace local-network --json"):
        assert command in text
    for example in (
        "solve-typical-diagnosis.json",
        "solve-trace-only-evidence.json",
        "verify-fallback.json",
        "solve-no-evidence.json",
        "trace-correlated-signals.json",
    ):
        assert f"docs/examples/local-network-json/{example}" in text


def test_documented_examples_are_valid_json_contracts():
    examples = {
        "solve-typical-diagnosis.json": SOLVE_REQUIRED_KEYS,
        "solve-trace-only-evidence.json": SOLVE_REQUIRED_KEYS,
        "verify-fallback.json": VERIFY_REQUIRED_KEYS,
        "solve-no-evidence.json": SOLVE_REQUIRED_KEYS,
        "trace-correlated-signals.json": TRACE_REQUIRED_KEYS,
    }

    for name, required_keys in examples.items():
        payload = json.loads((EXAMPLE_DIR / name).read_text())
        _assert_required_key_order(payload, required_keys)
        assert payload["command"] in {"solve local-network", "verify local-network", "trace local-network"}


def test_schema_contract_allows_backwards_compatible_additions_after_required_keys():
    payload = json.loads((EXAMPLE_DIR / "solve-typical-diagnosis.json").read_text())
    payload["future_optional_field"] = {"safe": True}

    _assert_required_key_order(payload, SOLVE_REQUIRED_KEYS)


def test_no_evidence_json_contract_is_trace_first_and_has_empty_rule_matches(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _empty_snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["solve", "local-network", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    _assert_required_key_order(payload, SOLVE_REQUIRED_KEYS)
    assert payload["matched_rules"] == []
    assert payload["repair_candidates"][0]["id"] == "trace-local-network"
    assert payload["next_action"]["id"] == "trace-local-network"


def test_human_readable_solve_output_does_not_become_json(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: _empty_snapshot())
    runner = CliRunner()

    result = runner.invoke(app, ["solve", "local-network"])

    assert result.exit_code == 0
    assert result.stdout.startswith("Current diagnosis")
    try:
        json.loads(result.stdout)
    except json.JSONDecodeError:
        pass
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("human-readable solve output unexpectedly became JSON")


def _assert_required_key_order(payload: dict[str, object], required_keys: list[str]) -> None:
    actual_keys = list(payload)
    assert actual_keys[: len(required_keys)] == required_keys
