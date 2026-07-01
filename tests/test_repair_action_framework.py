from __future__ import annotations

from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.framework import (
    DiagnosticEvidence,
    DiagnosticModule,
    FrameworkDiagnosticEngine,
    RepairAction,
    RepairCommand,
    RepairPrecondition,
    RepairRollback,
    RepairSafety,
    RepairStatus,
    repair_candidate_to_json,
)
from macos_state_explorer.diagnostics.rules import DiagnosticRule


def _snapshot() -> Snapshot:
    return Snapshot(
        host="repair-host",
        observations=[Observation(collector="example", started_at=1, ended_at=2, payload={})],
    )


def _evidence_provider(snapshot: Snapshot, context=None):
    return [DiagnosticEvidence(id="E001", title="Signal", detail="Signal present.", source="example")]


def _repair_candidates(evidence, context=None):
    return {
        "repair-a": RepairAction.candidate(
            id="repair-a",
            title="Repair A",
            risk="Low: deterministic test repair.",
            manual_action="Run repair A.",
            expected_result="A is fixed.",
            verification_command="mse verify example --branch repair-a",
            fallback_branch="Collect trace.",
            evidence_ids=["E001"],
            action_id="action-a",
        )
    }


def _diagnosis_builder(evidence, matches, plan, context=None):
    return "Repairable diagnosis"


def _actions(executed: list[list[str]], precondition_satisfied: bool = True):
    def runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 0, "ok", ""

    return {
        "action-a": RepairAction(
            id="action-a",
            title="Run deterministic repair A",
            description="Executes one fixed command.",
            safety=RepairSafety.LOW,
            why_safe="Only touches deterministic test state and has no variable inputs.",
            commands=(RepairCommand(argv=("examplectl", "repair", "--fixed"), description="Run fixed repair."),),
            preconditions=(
                RepairPrecondition(
                    id="tool-available",
                    title="examplectl is available",
                    satisfied=precondition_satisfied,
                    detail="Injected precondition for tests.",
                ),
            ),
            rollback=RepairRollback(available=True, description="Run examplectl repair --undo."),
            runner=runner,
        )
    }


def _module(executed: list[list[str]], precondition_satisfied: bool = True) -> DiagnosticModule:
    return DiagnosticModule(
        id="example",
        command_name="example",
        evidence_provider=_evidence_provider,
        rules=(
            DiagnosticRule(
                id="rule-a",
                diagnosis_id="diag-a",
                required_evidence=("E001",),
                repair_recommendations=("repair-a",),
                explanation="A matched.",
            ),
        ),
        repair_candidates=_repair_candidates,
        diagnosis_builder=_diagnosis_builder,
        repair_actions=lambda evidence, candidates, context=None: _actions(executed, precondition_satisfied),
    )


def test_repair_action_dry_run_contract_does_not_execute_and_preserves_candidate_json():
    executed: list[list[str]] = []
    engine = FrameworkDiagnosticEngine(_module(executed))

    result = engine.repair(_snapshot(), action_id="action-a", dry_run=True)

    assert executed == []
    assert result.status is RepairStatus.DRY_RUN
    payload = result.to_json_dict()
    assert list(payload) == [
        "command",
        "module",
        "action_id",
        "candidate_id",
        "status",
        "dry_run",
        "safety_classification",
        "why_safe",
        "preconditions",
        "rollback",
        "executed_commands",
        "message",
    ]
    assert payload["command"] == "repair example"
    assert payload["dry_run"] is True
    assert payload["safety_classification"] == "low"
    assert payload["preconditions"][0]["satisfied"] is True
    assert payload["executed_commands"] == [
        {"argv": ["examplectl", "repair", "--fixed"], "description": "Run fixed repair.", "exit_code": None}
    ]

    candidate_payload = repair_candidate_to_json(engine.solve(_snapshot()).repair_plan[0])
    assert candidate_payload is not None
    assert list(candidate_payload) == [
        "id",
        "title",
        "risk",
        "manual_action",
        "expected_result",
        "verification_command",
        "fallback_branch",
        "evidence_ids",
    ]


def test_repair_action_execution_is_deterministic_and_idempotent_with_injected_runner():
    executed: list[list[str]] = []
    engine = FrameworkDiagnosticEngine(_module(executed))

    first = engine.repair(_snapshot(), action_id="action-a", dry_run=False)
    second = engine.repair(_snapshot(), action_id="action-a", dry_run=False)

    assert first.status is RepairStatus.SUCCESS
    assert second.status is RepairStatus.SUCCESS
    assert executed == [
        ["examplectl", "repair", "--fixed"],
        ["examplectl", "repair", "--fixed"],
    ]
    assert first.to_json_dict()["executed_commands"][0]["exit_code"] == 0


def test_repair_action_blocks_execution_when_preconditions_fail():
    executed: list[list[str]] = []
    engine = FrameworkDiagnosticEngine(_module(executed, precondition_satisfied=False))

    result = engine.repair(_snapshot(), action_id="action-a", dry_run=False)

    assert result.status is RepairStatus.BLOCKED
    assert executed == []
    assert result.to_json_dict()["preconditions"][0] == {
        "id": "tool-available",
        "title": "examplectl is available",
        "satisfied": False,
        "detail": "Injected precondition for tests.",
    }


def test_repair_defaults_to_ranked_candidate_action_when_action_id_is_omitted():
    executed: list[list[str]] = []
    engine = FrameworkDiagnosticEngine(_module(executed))

    result = engine.repair(_snapshot(), dry_run=True)

    assert result.action_id == "action-a"
    assert result.candidate_id == "repair-a"
