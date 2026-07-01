from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.local_network.evidence import (
    LocalNetworkEvidence,
    collect_local_network_evidence,
)

SolverEvidence = LocalNetworkEvidence


@dataclass(frozen=True)
class RepairCandidate:
    id: str
    title: str
    risk: str
    manual_action: str
    expected_result: str
    verification_command: str
    fallback_branch: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LocalNetworkSolution:
    diagnosis: str
    evidence: list[SolverEvidence]
    repair_plan: list[RepairCandidate]

    def render_text(self) -> str:
        primary = self.repair_plan[0]
        lines = [
            "Current diagnosis",
            f"- {self.diagnosis}",
            "",
            "Evidence",
        ]
        for evidence in self.evidence:
            state = "present" if evidence.present else "absent"
            provenance = f"; provenance {', '.join(evidence.provenance)}" if evidence.provenance else ""
            lines.append(
                f"- {evidence.id} [{state}, confidence {evidence.confidence:.0%}{provenance}] "
                f"{evidence.title}: {evidence.detail}"
            )

        lines.extend([
            "",
            "Repair candidate",
            f"- {primary.title}",
            f"- Manual only: {primary.manual_action}",
            f"- Evidence: {', '.join(primary.evidence_ids)}",
            "",
            "Risk",
            f"- {primary.risk}",
            "",
            "Expected result",
            f"- {primary.expected_result}",
            "",
            "Verification command",
            f"- {primary.verification_command}",
            "",
            "Fallback branch",
            f"- {primary.fallback_branch}",
            "",
            "Branch order",
        ])
        for index, candidate in enumerate(self.repair_plan, start=1):
            lines.append(
                f"{index}. {candidate.id} — {candidate.title} "
                f"(Evidence: {', '.join(candidate.evidence_ids)})"
            )
        lines.extend([
            "",
            "Supporting read-only commands",
            "- mse diagnose local-network",
            "- mse launchservices ~/Desktop/mse-launchservices",
            "- mse trace local-network --out ~/Desktop/mse-local-network-trace",
            "- mse collect ~/Desktop/mse-local-network-collect --fast",
        ])
        return "\n".join(lines)


def build_local_network_solution(snapshot: Snapshot, trace_analysis: dict[str, Any] | None = None) -> LocalNetworkSolution:
    evidence = collect_local_network_evidence(snapshot, trace_analysis=trace_analysis)
    evidence_by_id = {item.id: item for item in evidence}

    def present(evidence_id: str) -> bool:
        item = evidence_by_id.get(evidence_id)
        return bool(item and item.present)

    def present_ids(*evidence_ids: str) -> list[str]:
        return [evidence_id for evidence_id in evidence_ids if present(evidence_id)]

    trash_evidence = present_ids("LN-E002", "LN-E003", "LN-E006", "LN-E007") or ["LN-E007"]
    reinstall_evidence = present_ids("LN-E001", "LN-E002", "LN-E005", "LN-E006", "LN-E008") or ["LN-E001"]
    trace_evidence = present_ids("LN-E001", "LN-E004", "LN-E005", "LN-E009") or ["LN-E001"]

    empty_trash = RepairCandidate(
        id="manual-empty-trash-reboot",
        title="Empty Trash manually, then reboot and re-check Local Network",
        risk="Medium: Emptying Trash permanently removes items already placed there; the tool does not do this automatically.",
        manual_action="Review Trash in Finder yourself. If it only contains disposable Chrome/Google leftovers, empty it from Finder, reboot macOS, open Local Network, then rerun verification.",
        expected_result="LaunchServices should stop resolving trashed or orphaned Chrome registrations; the Local Network list should drop stale Chrome/Google entries if they came from trashed app bundles.",
        verification_command="mse diagnose local-network",
        fallback_branch="If Chrome/Google Local Network entries remain, continue with branch 2: manual Chrome reinstall.",
        evidence_ids=trash_evidence,
    )
    reinstall = RepairCandidate(
        id="manual-reinstall-chrome",
        title="Manually reinstall Google Chrome from a fresh download",
        risk="Low to medium: user-driven app reinstall; bookmarks/profile data should remain in the Chrome profile, but the tool will not remove or edit any files.",
        manual_action="Quit Chrome normally, download Chrome from Google, install it into /Applications, reboot, and open Chrome once. Do not use this tool to remove app bundles or profiles.",
        expected_result="A fresh signed /Applications registration should replace code-sign-clone or orphaned LaunchServices records as the active Chrome identity.",
        verification_command="mse diagnose local-network",
        fallback_branch="If Local Network still shows the same broken Chrome state, continue with branch 3: capture a focused trace.",
        evidence_ids=reinstall_evidence,
    )
    trace = RepairCandidate(
        id="trace-local-network",
        title="Run a focused Local Network trace while opening System Settings",
        risk="Low: read-only logging and filesystem observation; sudo may be requested by macOS for fs_usage/lsof visibility.",
        manual_action="Run the trace command, open System Settings → Privacy & Security → Local Network, wait 20–30 seconds, then stop the trace.",
        expected_result="The trace should identify whether SecurityPrivacyExtension, LaunchServices .csstore reads, TCC/REG, or another privacy cache is feeding the stale GUI entry.",
        verification_command="mse trace local-network --out ~/Desktop/mse-local-network-trace",
        fallback_branch="If the trace still does not identify a safe repair, collect a full read-only bundle with mse collect and inspect the generated evidence before proposing any higher-risk action.",
        evidence_ids=trace_evidence,
    )

    if present("LN-E007"):
        plan = [empty_trash, reinstall, trace]
    elif present("LN-E006") or present("LN-E002") or present("LN-E008"):
        plan = [reinstall, trace]
    elif present("LN-E004") or present("LN-E005") or present("LN-E009"):
        plan = [trace, reinstall]
    else:
        plan = [trace]

    if present("LN-E007"):
        diagnosis = (
            "The strongest evidence is a Chrome/Google LaunchServices identity in Trash; empty Trash is only "
            "ranked first because Trash evidence is present."
        )
    elif present("LN-E006"):
        diagnosis = (
            "Trace or LaunchServices evidence shows a Chrome code-sign-clone identity, so a manual Chrome reinstall "
            "is ranked before another trace capture."
        )
    elif present("LN-E002") or present("LN-E008"):
        diagnosis = (
            "TCC does not currently prove a Local Network permission row problem; the strongest branch is stale "
            "Chrome/Google identity data in LaunchServices that is not specifically tied to Trash, so reinstall is safer than emptying Trash."
        )
    elif present("LN-E004") or present("LN-E005") or present("LN-E009"):
        diagnosis = (
            "The fast snapshot lacks strong LaunchServices repair evidence, but trace signals implicate the Local Network privacy UI path; "
            "capture or inspect trace evidence before proposing manual app changes."
        )
    else:
        diagnosis = (
            "The current read-only snapshot does not contain enough stale LaunchServices evidence to repair safely; "
            "start with trace evidence before any manual repair beyond normal reboot/re-check."
        )

    return LocalNetworkSolution(diagnosis=diagnosis, evidence=evidence, repair_plan=plan)


def load_trace_analysis(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    trace_path = path.expanduser()
    analysis_path = trace_path / "analysis.json" if trace_path.is_dir() else trace_path
    if not analysis_path.exists():
        return None
    return json.loads(analysis_path.read_text())
