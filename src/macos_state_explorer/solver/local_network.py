from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from macos_state_explorer.core.model import Snapshot


@dataclass(frozen=True)
class SolverEvidence:
    id: str
    title: str
    detail: str
    source: str
    present: bool = True


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
            lines.append(f"- {evidence.id} [{state}] {evidence.title}: {evidence.detail}")

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

    orphan_evidence = [
        item.id
        for item in evidence
        if item.id in {"LN-E002", "LN-E003", "LN-E006"} and item.present
    ] or ["LN-E002"]
    reinstall_evidence = [
        item.id
        for item in evidence
        if item.id in {"LN-E001", "LN-E002", "LN-E004", "LN-E006"} and item.present
    ] or ["LN-E001"]
    trace_evidence = [
        item.id
        for item in evidence
        if item.id in {"LN-E001", "LN-E004", "LN-E005"} and item.present
    ] or ["LN-E001"]

    plan = [
        RepairCandidate(
            id="manual-empty-trash-reboot",
            title="Empty Trash manually, then reboot and re-check Local Network",
            risk="Medium: Emptying Trash permanently removes items already placed there; the tool does not do this automatically.",
            manual_action="Review Trash in Finder yourself. If it only contains disposable Chrome/Google leftovers, empty it from Finder, reboot macOS, open Local Network, then rerun verification.",
            expected_result="LaunchServices should stop resolving trashed or orphaned Chrome registrations; the Local Network list should drop stale Chrome/Google entries if they came from trashed app bundles.",
            verification_command="mse diagnose local-network",
            fallback_branch="If Chrome/Google Local Network entries remain, continue with branch 2: manual Chrome reinstall.",
            evidence_ids=orphan_evidence,
        ),
        RepairCandidate(
            id="manual-reinstall-chrome",
            title="Manually reinstall Google Chrome from a fresh download",
            risk="Low to medium: user-driven app reinstall; bookmarks/profile data should remain in the Chrome profile, but the tool will not remove or edit any files.",
            manual_action="Quit Chrome normally, download Chrome from Google, install it into /Applications, reboot, and open Chrome once. Do not use this tool to remove app bundles or profiles.",
            expected_result="A fresh signed /Applications registration should replace code-sign-clone or orphaned LaunchServices records as the active Chrome identity.",
            verification_command="mse diagnose local-network",
            fallback_branch="If Local Network still shows the same broken Chrome state, continue with branch 3: capture a focused trace.",
            evidence_ids=reinstall_evidence,
        ),
        RepairCandidate(
            id="trace-local-network",
            title="Run a focused Local Network trace while opening System Settings",
            risk="Low: read-only logging and filesystem observation; sudo may be requested by macOS for fs_usage/lsof visibility.",
            manual_action="Run the trace command, open System Settings → Privacy & Security → Local Network, wait 20–30 seconds, then stop the trace.",
            expected_result="The trace should identify whether SecurityPrivacyExtension, LaunchServices .csstore reads, TCC/REG, or another privacy cache is feeding the stale GUI entry.",
            verification_command="mse trace local-network --out ~/Desktop/mse-local-network-trace",
            fallback_branch="If the trace still does not identify a safe repair, collect a full read-only bundle with mse collect and inspect the generated evidence before proposing any higher-risk action.",
            evidence_ids=trace_evidence,
        ),
    ]

    if any(evidence_by_id.get(eid) and evidence_by_id[eid].present for eid in ["LN-E002", "LN-E003", "LN-E006"]):
        diagnosis = (
            "TCC does not currently prove a Local Network permission row problem; the strongest branch is stale "
            "Chrome/Google identity data in LaunchServices or a privacy cache backed by LaunchServices metadata."
        )
    else:
        diagnosis = (
            "The current read-only snapshot does not contain enough stale LaunchServices evidence to repair safely; "
            "start with trace evidence before any manual repair beyond normal reboot/re-check."
        )

    return LocalNetworkSolution(diagnosis=diagnosis, evidence=evidence, repair_plan=plan)


def collect_local_network_evidence(
    snapshot: Snapshot,
    trace_analysis: dict[str, Any] | None = None,
) -> list[SolverEvidence]:
    payloads = {observation.collector: observation.payload for observation in snapshot.observations}
    tcc = payloads.get("tcc", {})
    launchservices = payloads.get("launchservices", {})
    trace_analysis = trace_analysis or {}

    direct_ln = _stdout(tcc.get("direct_localnetwork_query"))
    tcc_hits = _tcc_term_hits(tcc, ["ktccservicelocalnetwork", "localnetwork"])
    has_localnetwork_rows = bool(direct_ln.strip() or tcc_hits)

    stale_entries = launchservices.get("stale_entries", []) or []
    stale_count = len(stale_entries)
    stale_blob = str(stale_entries).lower()
    candidate_files = _stdout(launchservices.get("candidate_files"))
    trace_blob = str(trace_analysis).lower()

    evidence = [
        SolverEvidence(
            id="LN-E001",
            title="No kTCCServiceLocalNetwork rows found",
            detail=(
                "The direct Local Network query and scanned TCC/REG hits are empty."
                if not has_localnetwork_rows
                else "TCC/REG data includes Local Network terms; inspect before assuming LaunchServices is primary."
            ),
            source="tcc",
            present=not has_localnetwork_rows,
        ),
        SolverEvidence(
            id="LN-E002",
            title="LaunchServices has stale/orphaned Chrome or Google registrations",
            detail=f"{stale_count} stale LaunchServices entries were reported.",
            source="launchservices",
            present=stale_count > 0,
        ),
        SolverEvidence(
            id="LN-E003",
            title="LaunchServices store files are in the evidence set",
            detail="LaunchServices candidate files include registry/cache paths used by System Settings." if candidate_files else "No LaunchServices candidate file list was captured in this snapshot.",
            source="launchservices",
            present=bool(candidate_files),
        ),
        SolverEvidence(
            id="LN-E004",
            title="SecurityPrivacyExtension appears in Local Network trace",
            detail="Trace analysis references SecurityPrivacyExtension.appex." if "securityprivacyextension" in trace_blob else "No SecurityPrivacyExtension trace evidence was provided to this solver run.",
            source="trace",
            present="securityprivacyextension" in trace_blob,
        ),
        SolverEvidence(
            id="LN-E005",
            title="LaunchServices .csstore files appear heavily in Local Network trace",
            detail="Trace analysis references LaunchServices .csstore access." if ".csstore" in trace_blob else "No .csstore trace evidence was provided to this solver run.",
            source="trace",
            present=".csstore" in trace_blob,
        ),
        SolverEvidence(
            id="LN-E006",
            title="com.google.Chrome.code_sign_clone appears in evidence",
            detail="Chrome code_sign_clone identity appears in LaunchServices or trace evidence." if "com.google.chrome.code_sign_clone" in stale_blob + trace_blob else "No code_sign_clone identity appears in this snapshot.",
            source="launchservices/trace",
            present="com.google.chrome.code_sign_clone" in stale_blob + trace_blob,
        ),
    ]
    return evidence


def _stdout(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("stdout", ""))
    return str(value or "")


def _tcc_term_hits(tcc_payload: dict[str, Any], needles: list[str]) -> list[str]:
    hits: list[str] = []
    for section_name in ("user_tcc", "system_tcc", "regdb"):
        section = tcc_payload.get(section_name, {})
        for hit in section.get("hits", []) if isinstance(section, dict) else []:
            blob = str(hit).lower()
            hits.extend(needle for needle in needles if needle in blob)
    direct_chrome = _stdout(tcc_payload.get("direct_chrome_query"))
    if direct_chrome:
        blob = direct_chrome.lower()
        hits.extend(needle for needle in needles if needle in blob)
    return hits
