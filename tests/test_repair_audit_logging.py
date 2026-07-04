from __future__ import annotations

import json

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
)
from macos_state_explorer.diagnostics.rules import DiagnosticRule


def _snapshot() -> Snapshot:
    return Snapshot(host="audit-host", observations=[Observation(collector="audit", started_at=1, ended_at=2, payload={})])


def _module(executed: list[list[str]], *, command_result: tuple[int, str, str] = (0, "ok", "")) -> DiagnosticModule:
    def runner(command: list[str]) -> tuple[int, str, str]:
        executed.append(command)
        return command_result

    def evidence_provider(snapshot: Snapshot, context=None):
        return [DiagnosticEvidence(id="E-AUDIT", title="Audit signal", detail="Audit signal present.", source="test")]

    def repair_candidates(evidence, context=None):
        return {
            "candidate-a": RepairAction.candidate(
                id="candidate-a",
                title="Candidate A",
                risk="Low: audit test only.",
                manual_action="Run audited action.",
                expected_result="Audit entry exists.",
                verification_command="mse verify audit --branch candidate-a",
                fallback_branch="Collect support bundle.",
                evidence_ids=["E-AUDIT"],
                action_id="action-a",
            )
        }

    def diagnosis_builder(evidence, matches, plan, context=None):
        return "Auditable diagnosis"

    def repair_actions(evidence, candidates, context=None):
        return {
            "action-a": RepairAction(
                id="action-a",
                title="Audited action",
                description="Runs one deterministic audited command.",
                safety=RepairSafety.LOW,
                why_safe="Test command uses a fixed injected runner.",
                commands=(RepairCommand(argv=("auditctl", "repair"), description="Run audited repair."),),
                preconditions=(RepairPrecondition("tool", "tool exists", True, "Injected."),),
                rollback=RepairRollback(True, "Run auditctl repair --undo.", {"undo": ["auditctl", "repair", "--undo"]}),
                files_touched=("/tmp/audit-state",),
                runner=runner,
            )
        }

    return DiagnosticModule(
        id="audit-module",
        command_name="audit-module",
        evidence_provider=evidence_provider,
        rules=(
            DiagnosticRule(
                id="rule-audit",
                diagnosis_id="diag-audit",
                required_evidence=("E-AUDIT",),
                repair_recommendations=("candidate-a",),
                explanation="Audit matched.",
            ),
        ),
        repair_candidates=repair_candidates,
        diagnosis_builder=diagnosis_builder,
        repair_actions=repair_actions,
    )


def _read_audit_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_repair_audit_log_records_dry_run_without_executing(tmp_path):
    executed: list[list[str]] = []
    audit_log = tmp_path / "repair-audit.jsonl"
    engine = FrameworkDiagnosticEngine(_module(executed))

    result = engine.repair(_snapshot(), dry_run=True, audit_log=audit_log)

    assert executed == []
    assert result.status is RepairStatus.DRY_RUN
    assert result.to_json_dict()["audit_log"] == str(audit_log)
    events = _read_audit_events(audit_log)
    assert len(events) == 1
    event = events[0]
    assert list(event) == [
        "timestamp",
        "module",
        "selected_action",
        "mode",
        "preconditions",
        "result",
        "files_touched",
        "rollback",
        "errors",
    ]
    assert event["module"] == "audit-module"
    assert event["selected_action"] == {"id": "action-a", "candidate_id": "candidate-a"}
    assert event["mode"] == "dry-run"
    assert event["preconditions"][0]["id"] == "tool"
    assert event["result"]["status"] == "DRY_RUN"
    assert event["files_touched"] == ["/tmp/audit-state"]
    assert event["rollback"]["available"] is True
    assert event["errors"] == []


def test_non_dry_run_requires_confirmation_and_is_audited(tmp_path):
    executed: list[list[str]] = []
    audit_log = tmp_path / "repair-audit.jsonl"
    engine = FrameworkDiagnosticEngine(_module(executed))

    result = engine.repair(_snapshot(), dry_run=False, audit_log=audit_log)

    assert result.status is RepairStatus.BLOCKED
    assert executed == []
    assert "confirmation" in result.errors[0].lower()
    event = _read_audit_events(audit_log)[0]
    assert event["mode"] == "execute"
    assert event["result"]["status"] == "BLOCKED"
    assert "confirmation" in event["errors"][0].lower()


def test_confirmed_execution_records_files_and_failure_errors(tmp_path):
    executed: list[list[str]] = []
    audit_log = tmp_path / "repair-audit.jsonl"
    engine = FrameworkDiagnosticEngine(_module(executed, command_result=(7, "", "boom")))

    result = engine.repair(_snapshot(), dry_run=False, confirmed=True, audit_log=audit_log)

    assert executed == [["auditctl", "repair"]]
    assert result.status is RepairStatus.FAILED
    assert result.files_touched == ("/tmp/audit-state",)
    assert result.errors == ("boom",)
    event = _read_audit_events(audit_log)[0]
    assert event["result"]["executed_commands"][0]["exit_code"] == 7
    assert event["files_touched"] == ["/tmp/audit-state"]
    assert event["errors"] == ["boom"]


def test_repair_audit_log_appends_json_lines(tmp_path):
    executed: list[list[str]] = []
    audit_log = tmp_path / "repair-audit.jsonl"
    engine = FrameworkDiagnosticEngine(_module(executed))

    engine.repair(_snapshot(), dry_run=True, audit_log=audit_log)
    engine.repair(_snapshot(), dry_run=True, audit_log=audit_log)

    assert len(_read_audit_events(audit_log)) == 2
