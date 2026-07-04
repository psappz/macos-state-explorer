from __future__ import annotations

import json

import pytest

from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.framework import (
    DiagnosticEvidence,
    DiagnosticModule,
    DiagnosticRegistry,
    FrameworkDiagnosticEngine,
    RepairCandidate,
    build_support_bundle,
    repair_candidate_to_json,
)
from macos_state_explorer.diagnostics.rules import DiagnosticRule


def _snapshot() -> Snapshot:
    return Snapshot(
        host="framework-host",
        created_at=123.0,
        observations=[Observation(collector="example", started_at=1, ended_at=2, payload={"ok": True})],
    )


def _provider(snapshot: Snapshot, context: dict[str, object] | None = None) -> list[DiagnosticEvidence]:
    assert snapshot.host == "framework-host"
    assert context == {"source": "test"}
    return [
        DiagnosticEvidence(
            id="E002",
            title="Second signal",
            detail="Optional signal is present.",
            source="example",
            present=True,
            confidence=0.7,
            provenance=["optional"],
        ),
        DiagnosticEvidence(
            id="E001",
            title="First signal",
            detail="Required signal is present.",
            source="example",
            present=True,
            confidence=0.9,
            provenance=["required"],
        ),
    ]


def _repair_factory(evidence: list[DiagnosticEvidence], context: dict[str, object] | None = None) -> dict[str, RepairCandidate]:
    assert [item.id for item in evidence] == ["E002", "E001"]
    return {
        "repair-b": RepairCandidate(
            id="repair-b",
            title="Repair B",
            risk="low",
            manual_action="Do B manually.",
            expected_result="B is fixed.",
            verification_command="mse verify example --branch repair-b",
            fallback_branch="Try repair A.",
            evidence_ids=["E002"],
        ),
        "repair-a": RepairCandidate(
            id="repair-a",
            title="Repair A",
            risk="low",
            manual_action="Do A manually.",
            expected_result="A is fixed.",
            verification_command="mse verify example --branch repair-a",
            fallback_branch="Collect trace.",
            evidence_ids=["E001"],
        ),
    }


def _diagnosis_builder(evidence, matches, plan, context=None):
    assert [match.rule_id for match in matches] == ["rule-a", "rule-b"]
    assert [candidate.id for candidate in plan] == ["repair-a", "repair-b"]
    return "Example diagnosis"


def _module(module_id: str = "example") -> DiagnosticModule:
    return DiagnosticModule(
        id=module_id,
        command_name="example",
        evidence_provider=_provider,
        rules=(
            DiagnosticRule(
                id="rule-b",
                diagnosis_id="example-b",
                required_evidence=("E002",),
                confidence=0.2,
                repair_recommendations=("repair-b",),
                priority=20,
                explanation="B matched.",
            ),
            DiagnosticRule(
                id="rule-a",
                diagnosis_id="example-a",
                required_evidence=("E001",),
                optional_evidence=("E002",),
                confidence=0.4,
                repair_recommendations=("repair-a", "repair-b"),
                priority=10,
                explanation="A matched.",
            ),
        ),
        repair_candidates=_repair_factory,
        diagnosis_builder=_diagnosis_builder,
        fallback_repair_order=("repair-b",),
        supporting_commands=("mse diagnose example", "mse trace example --out ~/Desktop/example-trace"),
    )


def test_framework_engine_runs_module_with_deterministic_order_and_json_contract():
    solution = FrameworkDiagnosticEngine(_module()).solve(_snapshot(), context={"source": "test"})

    payload = solution.to_json_dict()

    assert list(payload) == ["command", "diagnosis", "evidence", "matched_rules", "repair_candidates", "next_action"]
    assert payload["command"] == "solve example"
    assert payload["diagnosis"] == "Example diagnosis"
    assert [item["id"] for item in payload["evidence"]] == ["E001", "E002"]
    assert [item["id"] for item in payload["matched_rules"]] == ["rule-a", "rule-b"]
    assert [item["id"] for item in payload["repair_candidates"]] == ["repair-a", "repair-b"]
    assert payload["next_action"]["id"] == "repair-a"
    assert list(payload["evidence"][0]) == ["id", "title", "detail", "source", "present", "confidence", "provenance"]
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


def test_framework_registry_rejects_duplicates_and_lists_modules_sorted():
    registry = DiagnosticRegistry()
    registry.register(_module("zeta"))
    registry.register(_module("alpha"))

    assert [module.id for module in registry.modules()] == ["alpha", "zeta"]
    assert registry.get("alpha").command_name == "example"
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_module("alpha"))
    with pytest.raises(KeyError):
        registry.get("missing")


def test_framework_support_bundle_writer_is_reusable_and_deterministic(tmp_path):
    solution = FrameworkDiagnosticEngine(_module()).solve(_snapshot(), context={"source": "test"})
    bundle = tmp_path / "bundle"

    build_support_bundle(
        bundle,
        report_json={"command": "report example", "solution": solution.to_json_dict()},
        report_text="Example report\n",
        command_metadata={"command": "mse report example --bundle", "bundle_schema_version": 1},
        environment={"python_version": "test", "platform": "test", "system": "test", "machine": "test"},
    )

    assert sorted(path.name for path in bundle.iterdir()) == ["command.json", "environment.json", "report.json", "report.txt"]
    assert json.loads((bundle / "report.json").read_text())["command"] == "report example"
    assert (bundle / "report.txt").read_text() == "Example report\n"
    assert list(json.loads((bundle / "command.json").read_text())) == ["command", "bundle_schema_version"]


def test_repair_candidate_json_helper_accepts_none_for_verification_contracts():
    candidate = RepairCandidate(
        id="repair-a",
        title="Repair A",
        risk="low",
        manual_action="Do A manually.",
        expected_result="A is fixed.",
        verification_command="mse verify example --branch repair-a",
        fallback_branch="Collect trace.",
        evidence_ids=["E001"],
    )

    assert repair_candidate_to_json(None) is None
    assert repair_candidate_to_json(candidate)["id"] == "repair-a"


def test_support_bundle_refuses_file_path(tmp_path):
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("already here")

    with pytest.raises(ValueError, match="not a directory"):
        build_support_bundle(
            file_path,
            report_json={},
            report_text="",
            command_metadata={},
            environment={},
        )
