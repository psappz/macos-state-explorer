from __future__ import annotations

import platform
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import build_support_bundle
from macos_state_explorer.diagnostics.local_network.verification import LocalNetworkVerification, verify_local_network
from macos_state_explorer.launchservices.analysis import LaunchServicesAnalysis, analysis_from_snapshot_payload, analysis_records_from_snapshot_payload
from macos_state_explorer.launchservices.generations import analyze_generations
from macos_state_explorer.launchservices.outcome import build_launchservices_outcome, read_execute_plan_audit_history, render_launchservices_outcome, render_outcome_summary
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance, render_launchservices_provenance, render_provenance_summary
from macos_state_explorer.launchservices.remediation_plan import render_remediation_plan_summary
from macos_state_explorer.solver.local_network import LocalNetworkSolution, build_local_network_solution


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
        payload["launchservices_analysis"] = (
            self.launchservices_analysis.to_json_dict()
            if self.launchservices_analysis
            else None
        )
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
    bundle = build_support_bundle(
        bundle_path,
        report_json=report.to_json_dict(),
        report_text=report.render_text(),
        command_metadata={
            "command": "mse report local-network --bundle",
            "branch": branch_id,
            "trace": _trace_metadata(trace_path),
            "launchservices_audit_log": _trace_metadata(launchservices_audit_log),
            "bundle_schema_version": 1,
        },
        environment=_environment_summary(),
        artifact_sources={"trace": trace_path} if trace_path is not None else None,
    )
    if report.launchservices_analysis is not None:
        (bundle / "launchservices-analysis.json").write_text(
            json.dumps(report.launchservices_analysis.to_json_dict(), indent=2, ensure_ascii=False) + "\n"
        )
    outcome = _report_outcome(report, launchservices_audit_log or report.launchservices_audit_log)
    (bundle / "outcome.json").write_text(json.dumps(outcome.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "outcome.txt").write_text(render_launchservices_outcome(outcome) + "\n")
    provenance = _report_provenance(report)
    (bundle / "provenance.json").write_text(json.dumps(provenance.to_json_dict(), indent=2, ensure_ascii=False) + "\n")
    (bundle / "provenance.txt").write_text(render_launchservices_provenance(provenance) + "\n")
    return bundle


def _report_outcome(report: LocalNetworkReport, audit_log: Path | Sequence[Path] | None = None):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_launchservices_outcome(analyze_generations(analysis_records_from_snapshot_payload(payload)), audit_history=read_execute_plan_audit_history(audit_log))


def _report_provenance(report: LocalNetworkReport):
    payload = next((observation.payload for observation in report.snapshot.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return build_launchservices_provenance(analyze_generations(analysis_records_from_snapshot_payload(payload)))


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
        },
        "signals": trace_analysis.get("correlation_summary", []),
        "candidate_paths": trace_analysis.get("candidate_paths", []),
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
            "kinds": ["directory" if path.is_dir() else "file" if path.is_file() else "missing" for path in paths],
        }
    expanded = Path(trace_path).expanduser()
    return {
        "provided": True,
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
