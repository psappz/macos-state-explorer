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
from macos_state_explorer.launchservices.producer_evidence import build_launchservices_producer_evidence, local_network_producer_evidence_summary
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance, local_network_provenance_summary
from macos_state_explorer.launchservices.remediation_plan import plan_launchservices_remediation, remediation_plan_summary
from macos_state_explorer.networkextension_state import build_networkextension_state, default_networkextension_roots, networkextension_state_summary
from macos_state_explorer.trace_correlation import build_trace_correlation_evidence, trace_correlation_summary
from macos_state_explorer.tracers.local_network import build_trace_timeline, trace_timeline_summary

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
        launchservices_provenance_summary=_launchservices_provenance_summary(snapshot),
        launchservices_producer_evidence_summary=_launchservices_producer_evidence_summary(snapshot, trace_analysis),
        trace_correlation_summary=_trace_correlation_summary(trace_analysis),
        trace_timeline_summary=_trace_timeline_summary(trace_analysis),
        networkextension_state_summary=_networkextension_state_summary(),
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


def _launchservices_provenance_summary(snapshot: Snapshot) -> dict[str, Any]:
    payload = next((observation.payload for observation in snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    records = analysis_records_from_snapshot_payload(payload)
    provenance = build_launchservices_provenance(analyze_generations(records))
    return local_network_provenance_summary(provenance)


def _launchservices_producer_evidence_summary(snapshot: Snapshot, trace_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    producer_evidence = build_launchservices_producer_evidence(snapshot, trace_analysis=trace_analysis)
    return local_network_producer_evidence_summary(producer_evidence)


def _trace_correlation_summary(trace_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    return trace_correlation_summary(build_trace_correlation_evidence(trace_analysis))


def _trace_timeline_summary(trace_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    return trace_timeline_summary(build_trace_timeline(trace_analysis))


def _networkextension_state_summary() -> dict[str, Any]:
    return networkextension_state_summary(build_networkextension_state(default_networkextension_roots()))


def load_trace_analysis(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    trace_path = path.expanduser()
    analysis_path = trace_path / "analysis.json" if trace_path.is_dir() else trace_path
    if not analysis_path.exists():
        return None
    return json.loads(analysis_path.read_text())
