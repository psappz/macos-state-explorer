from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace
from typing import Any, Sequence

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import (
    DiagnosticModule,
    DiagnosticSolution,
    FrameworkDiagnosticEngine,
    RepairCandidate as RepairCandidate,
    repair_candidate_to_json as repair_candidate_to_json,
)
from macos_state_explorer.diagnostics.local_network.evidence import LocalNetworkEvidence, collect_local_network_evidence
from macos_state_explorer.diagnostics.local_network.module import LOCAL_NETWORK_MODULE
from macos_state_explorer.launchservices.analysis import analysis_records_from_snapshot_payload
from macos_state_explorer.launchservices.generations import analyze_generations
from macos_state_explorer.launchservices.outcome import build_launchservices_outcome, outcome_summary, read_execute_plan_audit_history
from macos_state_explorer.launchservices.remediation_plan import plan_launchservices_remediation, remediation_plan_summary

SolverEvidence = LocalNetworkEvidence
LocalNetworkSolution = DiagnosticSolution


def build_local_network_solution(
    snapshot: Snapshot,
    trace_analysis: dict[str, Any] | None = None,
    *,
    launchservices_audit_log: Path | Sequence[Path] | None = None,
) -> LocalNetworkSolution:
    module = DiagnosticModule(
        id=LOCAL_NETWORK_MODULE.id,
        command_name=LOCAL_NETWORK_MODULE.command_name,
        evidence_provider=_solver_evidence_provider,
        rules=LOCAL_NETWORK_MODULE.rules,
        repair_candidates=LOCAL_NETWORK_MODULE.repair_candidates,
        diagnosis_builder=LOCAL_NETWORK_MODULE.diagnosis_builder,
        repair_actions=LOCAL_NETWORK_MODULE.repair_actions,
        fallback_repair_order=LOCAL_NETWORK_MODULE.fallback_repair_order,
        supporting_commands=LOCAL_NETWORK_MODULE.supporting_commands,
    )
    solution = FrameworkDiagnosticEngine(module).solve(snapshot, context={"trace_analysis": trace_analysis})
    return replace(
        solution,
        remediation_plan_summary=_launchservices_remediation_summary(snapshot),
        launchservices_outcome_summary=_launchservices_outcome_summary(snapshot, launchservices_audit_log),
    )


def _solver_evidence_provider(snapshot: Snapshot, context: dict[str, Any] | None = None) -> list[LocalNetworkEvidence]:
    context = context or {}
    trace_analysis = context.get("trace_analysis")
    return collect_local_network_evidence(
        snapshot,
        trace_analysis=trace_analysis if isinstance(trace_analysis, dict) else None,
    )


def _launchservices_remediation_summary(snapshot: Snapshot) -> dict[str, Any]:
    payload = next((observation.payload for observation in snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    records = analysis_records_from_snapshot_payload(payload)
    plan = plan_launchservices_remediation(analyze_generations(records))
    return remediation_plan_summary(plan)


def _launchservices_outcome_summary(snapshot: Snapshot, audit_log: Path | Sequence[Path] | None = None) -> dict[str, Any]:
    payload = next((observation.payload for observation in snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    records = analysis_records_from_snapshot_payload(payload)
    outcome = build_launchservices_outcome(analyze_generations(records), audit_history=read_execute_plan_audit_history(audit_log))
    return outcome_summary(outcome)


def load_trace_analysis(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    trace_path = path.expanduser()
    analysis_path = trace_path / "analysis.json" if trace_path.is_dir() else trace_path
    if not analysis_path.exists():
        return None
    return json.loads(analysis_path.read_text())
