from __future__ import annotations

import json
import platform
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import build_support_bundle
from macos_state_explorer.diagnostics.local_network.verification import LocalNetworkVerification, verify_local_network
from macos_state_explorer.launchservices.analysis import LaunchServicesAnalysis, analysis_from_snapshot_payload, analysis_records_from_snapshot_payload
from macos_state_explorer.launchservices.cleanup_checklist import build_launchservices_cleanup_checklist, local_network_cleanup_checklist_summary, render_cleanup_checklist_summary, render_launchservices_cleanup_checklist
from macos_state_explorer.launchservices.cleanup_verification import build_launchservices_cleanup_verification, local_network_cleanup_verification_summary, render_cleanup_verification_summary, render_launchservices_cleanup_verification
from macos_state_explorer.launchservices.generations import analyze_generations
from macos_state_explorer.launchservices.outcome import build_launchservices_outcome, read_execute_plan_audit_history, render_launchservices_outcome, render_outcome_summary
from macos_state_explorer.launchservices.producer_evidence import build_launchservices_producer_evidence, render_launchservices_producer_evidence, render_producer_evidence_summary
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance, render_launchservices_provenance, render_provenance_summary
from macos_state_explorer.launchservices.regeneration import build_launchservices_regeneration, local_network_regeneration_summary, render_launchservices_regeneration, render_regeneration_summary
from macos_state_explorer.launchservices.remediation_plan import render_remediation_plan_summary
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation, networkextension_candidate_validation_summary, render_networkextension_candidate_validation, render_networkextension_candidate_validation_summary
from macos_state_explorer.networkextension_correlation import build_networkextension_correlation, networkextension_correlation_summary, render_networkextension_correlation, render_networkextension_correlation_summary
from macos_state_explorer.networkextension_object_graph import build_networkextension_object_graph, networkextension_object_graph_summary, render_networkextension_object_graph, render_networkextension_object_graph_summary
from macos_state_explorer.networkextension_raw_references import build_networkextension_raw_references, networkextension_raw_references_summary, render_networkextension_raw_references, render_networkextension_raw_references_summary
from macos_state_explorer.networkextension_repair_candidates import build_networkextension_repair_candidates, networkextension_repair_candidates_summary, render_networkextension_repair_candidates, render_networkextension_repair_candidates_summary
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview, networkextension_repair_plan_preview_summary, render_networkextension_repair_plan_preview, render_networkextension_repair_plan_preview_summary
from macos_state_explorer.networkextension_repair_transaction_package import build_networkextension_repair_transaction_package, networkextension_repair_transaction_package_summary, render_networkextension_repair_transaction_package, render_networkextension_repair_transaction_package_summary
from macos_state_explorer.networkextension_manual_repair_runbook import build_networkextension_manual_repair_runbook, networkextension_manual_repair_runbook_summary, render_networkextension_manual_repair_runbook, render_networkextension_manual_repair_runbook_summary
from macos_state_explorer.networkextension_repair_simulation import build_networkextension_repair_simulation, networkextension_repair_simulation_summary, render_networkextension_repair_simulation, render_networkextension_repair_simulation_summary
from macos_state_explorer.networkextension_repair_artifact import build_networkextension_repair_artifact, networkextension_repair_artifact_not_generated, networkextension_repair_artifact_summary, render_networkextension_repair_artifact, render_networkextension_repair_artifact_summary
from macos_state_explorer.networkextension_state import build_networkextension_state, default_networkextension_roots, networkextension_state_summary, render_networkextension_state, render_networkextension_state_summary
from macos_state_explorer.solver.local_network import LocalNetworkSolution, build_local_network_solution
from macos_state_explorer.trace_correlation import build_trace_correlation_evidence, render_trace_correlation_evidence, render_trace_correlation_summary
from macos_state_explorer.tracers.local_network import build_trace_timeline, render_trace_timeline


@dataclass(frozen=True)
class LocalNetworkReport:
    snapshot: Snapshot
    solution: LocalNetworkSolution
    verification: LocalNetworkVerification
    trace_analysis: dict[str, Any] | None = None
    launchservices_analysis: LaunchServicesAnalysis | None = None
    launchservices_audit_log: Path | Sequence[Path] | None = None

    def to_json_dict(self) -> dict[str, Any]:
        solution_json = self.solution.to_json_dict()
        verification_json = self.verification.to_json_dict()
        verification_json.pop("command", None)
        payload = {
            "command": "report local-network",
            "system_context": _system_context_to_json(self.snapshot),
            "trace": _trace_to_json(self.trace_analysis),
            "diagnosis": solution_json["diagnosis"],
            "evidence": solution_json["evidence"],
            "matched_rules": solution_json["matched_rules"],
            "repair_candidates": solution_json["repair_candidates"],
            "verification": verification_json,
            "next_actions": _next_actions_to_json(self.solution, self.verification, self.trace_analysis),
        }
        if self.solution.remediation_plan_summary is not None:
            payload["remediation_plan_summary"] = self.solution.remediation_plan_summary
        if self.solution.launchservices_outcome_summary is not None:
            payload["launchservices_outcome_summary"] = self.solution.launchservices_outcome_summary
        if self.solution.launchservices_provenance_summary is not None:
            payload["launchservices_provenance_summary"] = self.solution.launchservices_provenance_summary
        if self.solution.launchservices_producer_evidence_summary is not None:
            payload["launchservices_producer_evidence_summary"] = self.solution.launchservices_producer_evidence_summary
        if self.solution.trace_correlation_summary is not None:
            payload["trace_correlation_summary"] = self.solution.trace_correlation_summary
        if self.solution.trace_timeline_summary is not None:
            payload["trace_timeline_summary"] = self.solution.trace_timeline_summary
        payload["launchservices_regeneration_summary"] = local_network_regeneration_summary(_report_regeneration(self, self.launchservices_audit_log))
        payload["launchservices_cleanup_checklist_summary"] = local_network_cleanup_checklist_summary(_report_cleanup_checklist(self))
        payload["launchservices_cleanup_verification_summary"] = local_network_cleanup_verification_summary(_report_cleanup_verification(self))
        payload["networkextension_state_summary"] = networkextension_state_summary(_report_networkextension_state())
        payload["networkextension_correlation_summary"] = networkextension_correlation_summary(_report_networkextension_correlation(self))
        payload["networkextension_raw_references_summary"] = networkextension_raw_references_summary(_report_networkextension_raw_references())
        payload["networkextension_object_graph_summary"] = networkextension_object_graph_summary(_report_networkextension_object_graph())
        payload["networkextension_repair_candidates_summary"] = networkextension_repair_candidates_summary(_report_networkextension_repair_candidates())
        payload["networkextension_candidate_validation_summary"] = networkextension_candidate_validation_summary(_report_networkextension_candidate_validation(self))
        payload["networkextension_repair_plan_preview_summary"] = networkextension_repair_plan_preview_summary(_report_networkextension_repair_plan_preview(self))
        payload["networkextension_repair_transaction_package_summary"] = networkextension_repair_transaction_package_summary(_report_networkextension_repair_transaction_package(self))
        payload["networkextension_manual_repair_runbook_summary"] = networkextension_manual_repair_runbook_summary(_report_networkextension_manual_repair_runbook(self))
        payload["networkextension_repair_simulation_summary"] = networkextension_repair_simulation_summary(_report_networkextension_repair_simulation(self))
        payload["networkextension_repair_artifact_summary"] = networkextension_repair_artifact_summary(_report_networkextension_repair_artifact(self))
        payload["launchservices_analysis"] = (
            self.launchservices_analysis.to_json_dict()
            if self.launchservices_analysis
            else None
        )
        payload["audit_context"] = _audit_context_to_json(self.launchservices_audit_log, self.solution.launchservices_outcome_summary)
        return payload

    def render_text(self) -> str:
        payload = self.to_json_dict()
        lines = [
            "Local Network diagnostic report",
            "",
            "System context",
            f"- Host: {payload['system_context']['host']}",
            f"- Snapshot schema version: {payload['system_context']['snapshot_schema_version']}",
            f"- Snapshot created at: {payload['system_context']['snapshot_created_at']}",
            f"- Observations: {payload['system_context']['observation_count']}",
            f"- Collectors: {', '.join(payload['system_context']['observation_collectors'])}",
            f"- Audit context: {'available' if payload['audit_context']['available'] else 'unavailable'}",
            "",
            "Trace summary",
        ]
        trace = payload["trace"]
        lines.append(f"- Available: {trace['available']}")
        if trace["signals"]:
            for signal in trace["signals"]:
                lines.append(
                    f"- {signal['signal']}: {signal['count']} "
                    f"({', '.join(signal.get('sources', []))}) — {signal['description']}"
                )
        else:
            lines.append("- No trace signals attached to this report.")

        lines.extend([
            "",
            "Diagnosis",
            f"- {payload['diagnosis']}",
            "",
            "Evidence",
        ])
        for evidence in payload["evidence"]:
            state = "present" if evidence["present"] else "absent"
            provenance = f"; provenance {', '.join(evidence['provenance'])}" if evidence["provenance"] else ""
            lines.append(
                f"- {evidence['id']} [{state}, confidence {evidence['confidence']:.0%}{provenance}] "
                f"{evidence['title']}: {evidence['detail']}"
            )

        if payload.get("remediation_plan_summary"):
            lines.extend(["", render_remediation_plan_summary(payload["remediation_plan_summary"])])
        if payload.get("launchservices_outcome_summary"):
            lines.extend(["", render_outcome_summary(payload["launchservices_outcome_summary"])])
        if payload.get("launchservices_provenance_summary"):
            lines.extend(["", render_provenance_summary(payload["launchservices_provenance_summary"])])
        if payload.get("launchservices_producer_evidence_summary"):
            lines.extend(["", render_producer_evidence_summary(payload["launchservices_producer_evidence_summary"])])
        if payload.get("trace_correlation_summary"):
            lines.extend(["", render_trace_correlation_summary(payload["trace_correlation_summary"])])
        if payload.get("trace_timeline_summary"):
            lines.extend(["", _render_trace_timeline_summary(payload["trace_timeline_summary"])])
        if payload.get("launchservices_regeneration_summary"):
            lines.extend(["", render_regeneration_summary(payload["launchservices_regeneration_summary"])])
        if payload.get("launchservices_cleanup_checklist_summary"):
            lines.extend(["", render_cleanup_checklist_summary(payload["launchservices_cleanup_checklist_summary"])])
        if payload.get("launchservices_cleanup_verification_summary"):
            lines.extend(["", render_cleanup_verification_summary(payload["launchservices_cleanup_verification_summary"])])
        if payload.get("networkextension_state_summary"):
            lines.extend(["", render_networkextension_state_summary(payload["networkextension_state_summary"])])
        if payload.get("networkextension_correlation_summary"):
            lines.extend(["", render_networkextension_correlation_summary(payload["networkextension_correlation_summary"])])
        if payload.get("networkextension_raw_references_summary"):
            lines.extend(["", render_networkextension_raw_references_summary(payload["networkextension_raw_references_summary"])])
        if payload.get("networkextension_object_graph_summary"):
            lines.extend(["", render_networkextension_object_graph_summary(payload["networkextension_object_graph_summary"])])
        if payload.get("networkextension_repair_candidates_summary"):
            lines.extend(["", render_networkextension_repair_candidates_summary(payload["networkextension_repair_candidates_summary"])])
        if payload.get("networkextension_candidate_validation_summary"):
            lines.extend(["", render_networkextension_candidate_validation_summary(payload["networkextension_candidate_validation_summary"])])
        if payload.get("networkextension_repair_plan_preview_summary"):
            lines.extend(["", render_networkextension_repair_plan_preview_summary(payload["networkextension_repair_plan_preview_summary"])])
        if payload.get("networkextension_repair_transaction_package_summary"):
            lines.extend(["", render_networkextension_repair_transaction_package_summary(payload["networkextension_repair_transaction_package_summary"])])
        if payload.get("networkextension_manual_repair_runbook_summary"):
            lines.extend(["", render_networkextension_manual_repair_runbook_summary(payload["networkextension_manual_repair_runbook_summary"])])
        if payload.get("networkextension_repair_simulation_summary"):
            lines.extend(["", render_networkextension_repair_simulation_summary(payload["networkextension_repair_simulation_summary"])])
        if payload.get("networkextension_repair_artifact_summary"):
            lines.extend(["", render_networkextension_repair_artifact_summary(payload["networkextension_repair_artifact_summary"])])

        lines.append("")
        lines.append("Matched rules")
        if payload["matched_rules"]:
            for rule in payload["matched_rules"]:
                lines.append(f"- {rule['id']} → {rule['diagnosis_id']}")
                lines.append(f"  Required evidence: {', '.join(rule['matched_required_evidence'])}")
                if rule["matched_optional_evidence"]:
                    lines.append(f"  Optional evidence: {', '.join(rule['matched_optional_evidence'])}")
                lines.append(f"  Recommendations: {', '.join(rule['repair_recommendations'])}")
        else:
            lines.append("- No rules matched.")

        lines.extend(["", "Repair ranking"])
        for index, candidate in enumerate(payload["repair_candidates"], start=1):
            lines.append(f"{index}. {candidate['id']} — {candidate['title']}")
            lines.append(f"   Risk: {candidate['risk']}")
            lines.append(f"   Evidence: {', '.join(candidate['evidence_ids'])}")
            lines.append(f"   Verify: {candidate['verification_command']}")

        verification = payload["verification"]
        lines.extend(
            [
                "",
                "Verification state",
                f"- Verification: {verification['status']}",
                f"- Branch: {verification['branch_id']}",
                f"- Transition: {verification['transition']}",
                f"- Expected change: {verification['expected_change']}",
                f"- Observed result: {verification['observed_result']}",
                f"- Evidence IDs: {', '.join(verification['evidence_ids']) if verification['evidence_ids'] else 'none'}",
                "",
                "Next actions",
            ]
        )
        for action in payload["next_actions"]:
            command = f" — {action['command']}" if action.get("command") else ""
            lines.append(f"- {action['type']}: {action['step']}{command}")
        return "\n".join(lines)


def write_local_network_support_bundle(
    report: LocalNetworkReport,
    bundle_path: Path,
    *,
    branch_id: str,
    trace_path: Path | None = None,
    launchservices_audit_log: Path | Sequence[Path] | None = None,
) -> Path:
    effective_audit_log = launchservices_audit_log if launchservices_audit_log is not None else report.launchservices_audit_log
    effective_report = replace(
        report,
        solution=build_local_network_solution(
            report.snapshot,
            trace_analysis=report.trace_analysis,
            launchservices_audit_log=effective_audit_log,
        ),
        launchservices_audit_log=effective_audit_log,
    )
    bundle = build_support_bundle(
        bundle_path,
        report_json=effective_report.to_json_dict(),
        report_text=effective_report.render_text(),
        command_metadata={
            "command": "mse report local-network --bundle",
            "branch": branch_id,
            "trace": _trace_metadata(trace_path),
            "launchservices_audit_log": _trace_metadata(effective_audit_log),
            "bundle_schema_version": 1,
        },
        environment=_environment_summary(),
        artifact_sources={"trace": trace_path} if trace_path is not None else None,
    )
    if effective_report.launchservices_analysis is not None:
        (bundle / "launchservices-analysis.json").write_text(
            json.dumps(effective_report.launchservices_analysis.to_json_dict(), indent=2, ensure_ascii=False) + "\n"
        )
    outcome = _report_outcome(effective_report, effective_audit_log)
    (bundle / "outcome.json").write_text(json.dumps(outcome.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "outcome.txt").write_text(render_launchservices_outcome(outcome) + "\n")
    provenance = _report_provenance(report)
    (bundle / "provenance.json").write_text(json.dumps(provenance.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "provenance.txt").write_text(render_launchservices_provenance(provenance) + "\n")
    producer_evidence = _report_producer_evidence(effective_report)
    (bundle / "producer-evidence.json").write_text(json.dumps(producer_evidence.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "producer-evidence.txt").write_text(render_launchservices_producer_evidence(producer_evidence) + "\n")
    trace_correlation = _report_trace_correlation(effective_report)
    (bundle / "trace-correlation.json").write_text(json.dumps(trace_correlation.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "trace-correlation.txt").write_text(render_trace_correlation_evidence(trace_correlation) + "\n")
    trace_timeline = _report_trace_timeline(effective_report)
    (bundle / "trace-timeline.json").write_text(json.dumps(trace_timeline.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "trace-timeline.txt").write_text(render_trace_timeline(trace_timeline) + "\n")
    regeneration = _report_regeneration(effective_report, effective_audit_log)
    (bundle / "regeneration.json").write_text(json.dumps(regeneration.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "regeneration.txt").write_text(render_launchservices_regeneration(regeneration) + "\n")
    cleanup_checklist = _report_cleanup_checklist(effective_report)
    (bundle / "cleanup-checklist.json").write_text(json.dumps(cleanup_checklist.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "cleanup-checklist.txt").write_text(render_launchservices_cleanup_checklist(cleanup_checklist) + "\n")
    cleanup_verification = _report_cleanup_verification(effective_report)
    (bundle / "cleanup-verification.json").write_text(json.dumps(cleanup_verification.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "cleanup-verification.txt").write_text(render_launchservices_cleanup_verification(cleanup_verification) + "\n")
    networkextension_state = _report_networkextension_state()
    (bundle / "networkextension-state.json").write_text(json.dumps(networkextension_state.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-state.txt").write_text(render_networkextension_state(networkextension_state) + "\n")
    networkextension_correlation = _report_networkextension_correlation(effective_report)
    (bundle / "networkextension-correlation.json").write_text(json.dumps(networkextension_correlation.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-correlation.txt").write_text(render_networkextension_correlation(networkextension_correlation) + "\n")
    networkextension_raw_references = _report_networkextension_raw_references()
    (bundle / "networkextension-raw-references.json").write_text(json.dumps(networkextension_raw_references.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-raw-references.txt").write_text(render_networkextension_raw_references(networkextension_raw_references) + "\n")
    networkextension_object_graph = _report_networkextension_object_graph()
    (bundle / "networkextension-object-graph.json").write_text(json.dumps(networkextension_object_graph.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-object-graph.txt").write_text(render_networkextension_object_graph(networkextension_object_graph) + "\n")
    networkextension_repair_candidates = _report_networkextension_repair_candidates()
    (bundle / "networkextension-repair-candidates.json").write_text(json.dumps(networkextension_repair_candidates.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-repair-candidates.txt").write_text(render_networkextension_repair_candidates(networkextension_repair_candidates) + "\n")
    networkextension_candidate_validation = _report_networkextension_candidate_validation(effective_report)
    (bundle / "networkextension-candidate-validation.json").write_text(json.dumps(networkextension_candidate_validation.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-candidate-validation.txt").write_text(render_networkextension_candidate_validation(networkextension_candidate_validation) + "\n")
    networkextension_repair_plan_preview = build_networkextension_repair_plan_preview(networkextension_candidate_validation)
    (bundle / "networkextension-repair-plan-preview.json").write_text(json.dumps(networkextension_repair_plan_preview.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-repair-plan-preview.txt").write_text(render_networkextension_repair_plan_preview(networkextension_repair_plan_preview) + "\n")
    networkextension_repair_transaction_package = build_networkextension_repair_transaction_package(networkextension_repair_plan_preview, default_networkextension_roots())
    (bundle / "networkextension-repair-transaction-package.json").write_text(json.dumps(networkextension_repair_transaction_package.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-repair-transaction-package.txt").write_text(render_networkextension_repair_transaction_package(networkextension_repair_transaction_package) + "\n")
    networkextension_manual_repair_runbook = build_networkextension_manual_repair_runbook(networkextension_repair_transaction_package, default_networkextension_roots())
    (bundle / "networkextension-manual-repair-runbook.json").write_text(json.dumps(networkextension_manual_repair_runbook.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-manual-repair-runbook.txt").write_text(render_networkextension_manual_repair_runbook(networkextension_manual_repair_runbook) + "\n")
    networkextension_repair_simulation = build_networkextension_repair_simulation(networkextension_manual_repair_runbook, default_networkextension_roots())
    (bundle / "networkextension-repair-simulation.json").write_text(json.dumps(networkextension_repair_simulation.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-repair-simulation.txt").write_text(render_networkextension_repair_simulation(networkextension_repair_simulation) + "\n")
    networkextension_repair_artifact = _build_networkextension_repair_artifact_or_metadata(
        networkextension_manual_repair_runbook,
        networkextension_repair_simulation,
        bundle / "networkextension-repair-artifact.plist",
    )
    (bundle / "networkextension-repair-artifact.json").write_text(json.dumps(networkextension_repair_artifact.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "networkextension-repair-artifact.txt").write_text(render_networkextension_repair_artifact(networkextension_repair_artifact) + "\n")
    return bundle


def _report_outcome(report: LocalNetworkReport, audit_log: Path | Sequence[Path] | None = None):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_launchservices_outcome(analyze_generations(analysis_records_from_snapshot_payload(payload)), audit_history=read_execute_plan_audit_history(audit_log))


def _report_provenance(report: LocalNetworkReport):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_launchservices_provenance(analyze_generations(analysis_records_from_snapshot_payload(payload)))


def _report_producer_evidence(report: LocalNetworkReport):
    return build_launchservices_producer_evidence(report.snapshot, trace_analysis=report.trace_analysis)


def _report_trace_correlation(report: LocalNetworkReport):
    return build_trace_correlation_evidence(report.trace_analysis)


def _report_trace_timeline(report: LocalNetworkReport):
    return build_trace_timeline(report.trace_analysis)


def _report_regeneration(report: LocalNetworkReport, audit_log: Path | Sequence[Path] | None = None):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_launchservices_regeneration(
        analyze_generations(analysis_records_from_snapshot_payload(payload)),
        trace_analysis=report.trace_analysis,
        audit_history=read_execute_plan_audit_history(audit_log),
    )


def _report_cleanup_checklist(report: LocalNetworkReport):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_launchservices_cleanup_checklist(
        analyze_generations(analysis_records_from_snapshot_payload(payload)),
        trace_analysis=report.trace_analysis,
    )


def _report_cleanup_verification(report: LocalNetworkReport):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_launchservices_cleanup_verification(analyze_generations(analysis_records_from_snapshot_payload(payload)))


def _report_networkextension_state():
    return build_networkextension_state(default_networkextension_roots())


def _report_networkextension_raw_references():
    return build_networkextension_raw_references(default_networkextension_roots())


def _report_networkextension_object_graph():
    return build_networkextension_object_graph(default_networkextension_roots())


def _report_networkextension_repair_candidates():
    return build_networkextension_repair_candidates(default_networkextension_roots())


def _report_networkextension_candidate_validation(report: LocalNetworkReport):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_networkextension_candidate_validation(default_networkextension_roots(), launchservices_entries=payload.get("entries", []))


def _report_networkextension_repair_plan_preview(report: LocalNetworkReport):
    return build_networkextension_repair_plan_preview(_report_networkextension_candidate_validation(report))


def _report_networkextension_repair_transaction_package(report: LocalNetworkReport):
    return build_networkextension_repair_transaction_package(_report_networkextension_repair_plan_preview(report), default_networkextension_roots())


def _report_networkextension_manual_repair_runbook(report: LocalNetworkReport):
    return build_networkextension_manual_repair_runbook(_report_networkextension_repair_transaction_package(report), default_networkextension_roots())


def _report_networkextension_repair_simulation(report: LocalNetworkReport):
    return build_networkextension_repair_simulation(_report_networkextension_manual_repair_runbook(report), default_networkextension_roots())


def _report_networkextension_repair_artifact(report: LocalNetworkReport):
    simulation = _report_networkextension_repair_simulation(report)
    runbook = _report_networkextension_manual_repair_runbook(report)
    with tempfile.TemporaryDirectory(prefix="mse-ne-repair-artifact-report-") as temp_dir:
        return _build_networkextension_repair_artifact_or_metadata(runbook, simulation, Path(temp_dir) / "networkextension-repair-artifact.plist")


def _build_networkextension_repair_artifact_or_metadata(runbook, simulation, output_path: Path):
    try:
        return build_networkextension_repair_artifact(runbook, simulation, output_path, default_networkextension_roots())
    except ValueError as error:
        return networkextension_repair_artifact_not_generated(str(error))


def _report_networkextension_correlation(report: LocalNetworkReport):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    records = analysis_records_from_snapshot_payload(payload)
    return build_networkextension_correlation(
        analyze_generations(records),
        records,
        roots=default_networkextension_roots(),
        trace_analysis=report.trace_analysis,
    )


def _render_trace_timeline_summary(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "High-Fidelity Trace Timeline Summary",
            f"- Events: {summary.get('event_count', 0)}",
            f"- Processes: {', '.join((summary.get('processes') or {}).keys()) or 'none'}",
            f"- Operations: {', '.join((summary.get('operations') or {}).keys()) or 'none'}",
        ]
    )


def build_local_network_report(
    snapshot: Snapshot,
    *,
    trace_analysis: dict[str, Any] | None = None,
    branch_id: str = "manual-empty-trash-reboot",
    launchservices_audit_log: Path | Sequence[Path] | None = None,
) -> LocalNetworkReport:
    solution = build_local_network_solution(snapshot, trace_analysis=trace_analysis, launchservices_audit_log=launchservices_audit_log)
    verification = verify_local_network(snapshot, expected_branch_id=branch_id, trace_analysis=trace_analysis)
    payload = next((observation.payload for observation in snapshot.observations if observation.collector == "launchservices"), {})
    return LocalNetworkReport(
        snapshot=snapshot,
        trace_analysis=trace_analysis,
        solution=solution,
        verification=verification,
        launchservices_audit_log=launchservices_audit_log,
        launchservices_analysis=analysis_from_snapshot_payload(payload if isinstance(payload, dict) else {}),
    )


def _system_context_to_json(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "host": snapshot.host,
        "snapshot_schema_version": snapshot.schema_version,
        "snapshot_created_at": snapshot.created_at,
        "observation_collectors": sorted({observation.collector for observation in snapshot.observations}),
        "observation_count": len(snapshot.observations),
    }


def _trace_to_json(trace_analysis: dict[str, Any] | None) -> dict[str, Any]:
    if trace_analysis is None:
        return {
            "available": False,
            "analysis": None,
            "signals": [],
            "candidate_paths": [],
        }
    return {
        "available": True,
        "analysis": {
            "created_at": trace_analysis.get("created_at"),
            "keyword_hits": trace_analysis.get("keyword_hits", {}),
            "signal_counts": trace_analysis.get("signal_counts", {}),
            "correlation_summary": trace_analysis.get("correlation_summary", []),
            "timeline_events": trace_analysis.get("timeline_events", []),
            "normalized_events": trace_analysis.get("normalized_events", []),
            "trace_timeline_summary": trace_analysis.get("trace_timeline_summary", {}),
        },
        "signals": trace_analysis.get("correlation_summary", []),
        "candidate_paths": trace_analysis.get("candidate_paths", []),
    }


def _audit_context_to_json(audit_log: Path | Sequence[Path] | None, outcome_summary: dict[str, Any] | None) -> dict[str, Any]:
    metadata = _trace_metadata(audit_log)
    source_count = int(metadata.get("count", 1 if metadata.get("provided") else 0))
    return {
        "available": bool(metadata.get("provided") or (outcome_summary or {}).get("audit_informed")),
        "source_count": source_count,
    }



def _environment_summary() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
    }


def _trace_metadata(trace_path: Path | Sequence[Path] | None) -> dict[str, Any]:
    if trace_path is None:
        return {"provided": False}
    if isinstance(trace_path, Sequence) and not isinstance(trace_path, (str, bytes, Path)):
        paths = [Path(item).expanduser() for item in trace_path]
        return {
            "provided": bool(paths),
            "count": len(paths),
            "paths": [str(path) for path in paths],
            "kinds": ["directory" if path.is_dir() else "file" if path.is_file() else "missing" for path in paths],
        }
    expanded = Path(trace_path).expanduser()
    return {
        "provided": True,
        "path": str(expanded),
        "kind": "directory" if expanded.is_dir() else "file" if expanded.is_file() else "missing",
    }



def _next_actions_to_json(
    solution: LocalNetworkSolution,
    verification: LocalNetworkVerification,
    trace_analysis: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if verification.next_repair_candidate:
        actions.append(
            {
                "type": "repair",
                "step": verification.next_step,
                "command": None,
                "candidate_id": verification.next_repair_candidate.id,
            }
        )
    elif solution.repair_plan:
        actions.append(
            {
                "type": "repair",
                "step": solution.repair_plan[0].manual_action,
                "command": None,
                "candidate_id": solution.repair_plan[0].id,
            }
        )
    actions.append(
        {
            "type": "verify",
            "step": verification.retry_guidance,
            "command": f"mse verify local-network --branch {verification.branch_id}",
            "candidate_id": verification.branch_id,
        }
    )
    trace_command = "mse trace local-network ~/Desktop/mse-local-network-trace"
    if trace_analysis is not None:
        trace_command = "mse solve local-network --trace ~/Desktop/mse-local-network-trace"
    actions.append(
        {
            "type": "trace",
            "step": verification.fallback_guidance,
            "command": trace_command,
            "candidate_id": "trace-local-network",
        }
    )
    return actions
