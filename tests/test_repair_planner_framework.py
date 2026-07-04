from __future__ import annotations

import json

from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.framework import (
    DiagnosticEvidence,
    DiagnosticModule,
    FrameworkDiagnosticEngine,
    RepairAction,
    RepairCommand,
    RepairPlanStatus,
    RepairPrecondition,
    RepairSafety,
    RepairVerification,
    repair_plan_audit_event,
)
from macos_state_explorer.diagnostics.rules import DiagnosticRule


def _snapshot(label: str = "before") -> Snapshot:
    return Snapshot(host=label, observations=[Observation(collector="example", started_at=1, ended_at=2, payload={})])


def _evidence_provider(snapshot: Snapshot, context=None):
    return [DiagnosticEvidence(id="E001", title="Signal", detail=f"Signal present on {snapshot.host}.", source="example")]


def _repair_candidates(evidence, context=None):
    return {
        "repair-a": RepairAction.candidate(
            id="repair-a",
            title="Repair A",
            risk="Low: deterministic first repair.",
            manual_action="Run repair A.",
            expected_result="A is fixed.",
            verification_command="mse verify example --branch repair-a",
            fallback_branch="Continue with B.",
            evidence_ids=["E001"],
            action_id="action-a",
        ),
        "repair-b": RepairAction.candidate(
            id="repair-b",
            title="Repair B",
            risk="Low: deterministic second repair.",
            manual_action="Run repair B.",
            expected_result="B is fixed.",
            verification_command="mse verify example --branch repair-b",
            fallback_branch="Collect trace.",
            evidence_ids=["E001"],
            action_id="action-b",
        ),
        "repair-manual": RepairAction.candidate(
            id="repair-manual",
            title="Manual-only Repair",
            risk="Medium: manual branch.",
            manual_action="Do the manual branch.",
            expected_result="Manual branch is fixed.",
            verification_command="mse verify example --branch repair-manual",
            fallback_branch="Continue with A.",
            evidence_ids=["E001"],
            action_id=None,
        ),
        "repair-high": RepairAction.candidate(
            id="repair-high",
            title="High-risk Repair",
            risk="High: should not be auto-run by the planner.",
            manual_action="Run high-risk branch manually.",
            expected_result="High-risk branch is fixed.",
            verification_command="mse verify example --branch repair-high",
            fallback_branch="Stop.",
            evidence_ids=["E001"],
            action_id="action-high",
        ),
    }


def _diagnosis_builder(evidence, matches, plan, context=None):
    return "Planner diagnosis"


def _module(executed: list[list[str]], verification_statuses: list[str], *, include_high: bool = False) -> DiagnosticModule:
    def runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return 0, "ok", ""

    def actions(evidence, candidates, context=None):
        return {
            "action-a": RepairAction(
                id="action-a",
                title="Action A",
                description="Runs A.",
                safety=RepairSafety.LOW,
                why_safe="A is a deterministic low-risk test command.",
                commands=(RepairCommand(argv=("examplectl", "repair-a"), description="Run A."),),
                preconditions=(RepairPrecondition("a-ready", "A ready", True, "Injected test precondition."),),
                runner=runner,
                files_touched=("/tmp/a",),
            ),
            "action-b": RepairAction(
                id="action-b",
                title="Action B",
                description="Runs B.",
                safety=RepairSafety.LOW,
                why_safe="B is a deterministic low-risk test command.",
                commands=(RepairCommand(argv=("examplectl", "repair-b"), description="Run B."),),
                runner=runner,
                files_touched=("/tmp/b",),
            ),
            "action-high": RepairAction(
                id="action-high",
                title="Action High",
                description="Runs high risk command.",
                safety=RepairSafety.HIGH,
                why_safe="High-risk action is intentionally not safe for automatic continuation.",
                commands=(RepairCommand(argv=("examplectl", "repair-high"), description="Run high risk."),),
                runner=runner,
                files_touched=("/tmp/high",),
            ),
        }

    def verifier(snapshot: Snapshot, candidate, context=None) -> RepairVerification:
        status = verification_statuses.pop(0)
        return RepairVerification(
            status=status,
            branch_id=candidate.id,
            observed_result=f"{candidate.id} verified as {status} on {snapshot.host}.",
            evidence_ids=["E001"],
            continues_workflow=status != "SUCCESS",
        )

    recommendations = ("repair-manual", "repair-a", "repair-b", "repair-high") if include_high else ("repair-manual", "repair-a", "repair-b")
    return DiagnosticModule(
        id="example",
        command_name="example",
        evidence_provider=_evidence_provider,
        rules=(
            DiagnosticRule(
                id="rule-plan",
                diagnosis_id="diag-plan",
                required_evidence=("E001",),
                repair_recommendations=recommendations,
                explanation="Planner rule matched.",
            ),
        ),
        repair_candidates=_repair_candidates,
        diagnosis_builder=_diagnosis_builder,
        repair_actions=actions,
        repair_verifier=verifier,
    )


def test_repair_plan_builds_steps_from_ranked_candidates_and_skips_manual_only_step():
    executed: list[list[str]] = []
    engine = FrameworkDiagnosticEngine(_module(executed, []))

    plan = engine.plan_repair(_snapshot())

    assert [step.candidate_id for step in plan.steps] == ["repair-manual", "repair-a", "repair-b"]
    assert [step.action_id for step in plan.steps] == [None, "action-a", "action-b"]
    assert plan.steps[0].skipped_reason == "No executable repair action is registered for this repair candidate."
    assert list(plan.to_json_dict()) == ["command", "module", "steps"]


def test_repair_plan_dry_run_is_deterministic_and_does_not_verify_or_execute():
    executed: list[list[str]] = []
    engine = FrameworkDiagnosticEngine(_module(executed, ["SUCCESS"]))

    result = engine.repair_plan(_snapshot(), dry_run=True)

    assert result.status is RepairPlanStatus.DRY_RUN
    assert executed == []
    assert [step_result.status for step_result in result.step_results] == ["SKIPPED", "DRY_RUN", "DRY_RUN"]
    assert all(step_result.verification is None for step_result in result.step_results)
    payload = result.to_json_dict()
    assert list(payload) == [
        "command",
        "module",
        "status",
        "dry_run",
        "confirmed",
        "plan",
        "step_results",
        "message",
        "audit_log",
    ]
    assert payload["plan"]["steps"][1]["action_id"] == "action-a"


def test_repair_plan_stops_after_first_successful_verification():
    executed: list[list[str]] = []
    snapshots = iter([_snapshot("after-a")])
    engine = FrameworkDiagnosticEngine(_module(executed, ["SUCCESS"]))

    result = engine.repair_plan(
        _snapshot("before"),
        dry_run=False,
        confirmed=True,
        snapshot_provider=lambda: next(snapshots),
    )

    assert result.status is RepairPlanStatus.SUCCESS
    assert executed == [["examplectl", "repair-a"]]
    assert [step_result.status for step_result in result.step_results] == ["SKIPPED", "SUCCESS"]
    assert result.step_results[-1].verification is not None
    assert result.step_results[-1].verification.status == "SUCCESS"
    assert "repair-a verified as SUCCESS on after-a" in result.step_results[-1].verification.observed_result


def test_repair_plan_continues_to_next_safe_step_after_failed_verification():
    executed: list[list[str]] = []
    snapshots = iter([_snapshot("after-a"), _snapshot("after-b")])
    engine = FrameworkDiagnosticEngine(_module(executed, ["FAILED", "SUCCESS"]))

    result = engine.repair_plan(
        _snapshot("before"),
        dry_run=False,
        confirmed=True,
        snapshot_provider=lambda: next(snapshots),
    )

    assert result.status is RepairPlanStatus.SUCCESS
    assert executed == [["examplectl", "repair-a"], ["examplectl", "repair-b"]]
    assert [step_result.status for step_result in result.step_results] == ["SKIPPED", "FAILED", "SUCCESS"]
    assert [step_result.verification.status if step_result.verification else None for step_result in result.step_results] == [
        None,
        "FAILED",
        "SUCCESS",
    ]


def test_repair_plan_blocks_before_high_risk_step_when_verification_fails():
    executed: list[list[str]] = []
    snapshots = iter([_snapshot("after-a"), _snapshot("after-b")])
    engine = FrameworkDiagnosticEngine(_module(executed, ["FAILED", "FAILED"], include_high=True))

    result = engine.repair_plan(
        _snapshot("before"),
        dry_run=False,
        confirmed=True,
        snapshot_provider=lambda: next(snapshots),
    )

    assert result.status is RepairPlanStatus.BLOCKED
    assert executed == [["examplectl", "repair-a"], ["examplectl", "repair-b"]]
    assert result.step_results[-1].candidate_id == "repair-high"
    assert result.step_results[-1].status == "BLOCKED"
    assert "not safe for automatic continuation" in result.step_results[-1].message


def test_repair_plan_audit_event_records_ordered_steps_and_verification(tmp_path):
    executed: list[list[str]] = []
    snapshots = iter([_snapshot("after-a")])
    audit_log = tmp_path / "repair-plan.jsonl"
    engine = FrameworkDiagnosticEngine(_module(executed, ["SUCCESS"]))

    result = engine.repair_plan(
        _snapshot("before"),
        dry_run=False,
        confirmed=True,
        audit_log=audit_log,
        snapshot_provider=lambda: next(snapshots),
    )

    assert result.audit_log == str(audit_log)
    event = json.loads(audit_log.read_text().splitlines()[0])
    expected = repair_plan_audit_event(result)
    assert event["timestamp"].endswith("Z")
    assert {key: value for key, value in event.items() if key != "timestamp"} == {
        key: value for key, value in expected.items() if key != "timestamp"
    }
    assert event["mode"] == "execute-plan"
    assert event["result"]["status"] == "SUCCESS"
    assert [step["candidate_id"] for step in event["result"]["step_results"]] == ["repair-manual", "repair-a"]
    assert event["result"]["step_results"][1]["verification"]["status"] == "SUCCESS"
