from __future__ import annotations

from typing import Any, Sequence

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticEvidence, DiagnosticModule, RepairCandidate
from macos_state_explorer.diagnostics.launchservices.evidence import collect_launchservices_evidence
from macos_state_explorer.diagnostics.launchservices.rules import LAUNCHSERVICES_RULES
from macos_state_explorer.diagnostics.rules import RuleMatch

LAUNCHSERVICES_SUPPORTING_COMMANDS = (
    "mse launchservices ~/Desktop/mse-launchservices",
    "mse collect ~/Desktop/mse-launchservices-collect --fast",
)


def launchservices_evidence_provider(
    snapshot: Snapshot,
    context: dict[str, Any] | None = None,
) -> list[DiagnosticEvidence]:
    return collect_launchservices_evidence(snapshot, context=context)


def launchservices_repair_candidates(
    evidence: Sequence[DiagnosticEvidence],
    context: dict[str, Any] | None = None,
) -> dict[str, RepairCandidate]:
    present_ids = [item.id for item in evidence if item.present]
    stale_ids = [item.id for item in evidence if item.present and item.id in {"LS-E001", "LS-E002", "LS-E003", "LS-E004"}]
    duplicate_ids = [item.id for item in evidence if item.present and item.id in {"LS-E003", "LS-E001", "LS-E002"}]
    candidate_ids = [item.id for item in evidence if item.present and item.id in {"LS-E004", "LS-E001", "LS-E003"}]
    fallback_ids = present_ids or ["LS-E004"]
    return {
        "review-stale-launchservices": RepairCandidate(
            id="review-stale-launchservices",
            title="Review stale LaunchServices registrations in the generated report",
            risk="Low: read-only review; no LaunchServices database reset or file deletion is performed.",
            manual_action="Open the LaunchServices report, review stale and missing-path app registrations, and confirm which apps are safe to reinstall or ignore.",
            expected_result="Support can identify whether stale or missing app records explain the observed LaunchServices behavior before any cleanup is considered.",
            verification_command="mse solve launchservices",
            fallback_branch="If the report is inconclusive, collect a support bundle and inspect duplicate bundle identifiers next.",
            evidence_ids=stale_ids or ["LS-E001"],
        ),
        "review-duplicate-bundle-identifiers": RepairCandidate(
            id="review-duplicate-bundle-identifiers",
            title="Review duplicate LaunchServices bundle identifiers",
            risk="Low: read-only review of duplicate bundle identifiers and their paths.",
            manual_action="Compare duplicate bundle IDs, paths, versions, and missing-path flags in the LaunchServices report before choosing any manual app reinstall.",
            expected_result="Duplicate bundle IDs are separated into active versus stale paths so the next manual action is evidence-backed.",
            verification_command="mse solve launchservices",
            fallback_branch="If duplicates remain ambiguous, collect a support bundle for offline inspection.",
            evidence_ids=duplicate_ids or ["LS-E003"],
        ),
        "collect-launchservices-support-bundle": RepairCandidate(
            id="collect-launchservices-support-bundle",
            title="Collect a LaunchServices support bundle",
            risk="Low: read-only bundle export; includes diagnostic JSON, report text, and environment summary.",
            manual_action="Run `mse report launchservices --bundle ~/Desktop/mse-launchservices-support` and share the generated directory with support.",
            expected_result="Support receives deterministic report JSON and text artifacts without destructive LaunchServices changes.",
            verification_command="mse report launchservices --bundle ~/Desktop/mse-launchservices-support",
            fallback_branch="If the bundle still lacks evidence, rerun `mse launchservices` and inspect the raw collector output.",
            evidence_ids=candidate_ids or fallback_ids,
        ),
    }


def launchservices_diagnosis_builder(
    evidence: Sequence[DiagnosticEvidence],
    rule_matches: Sequence[RuleMatch],
    repair_plan: Sequence[RepairCandidate],
    context: dict[str, Any] | None = None,
) -> str:
    present = {item.id for item in evidence if item.present}
    if {"LS-E001", "LS-E002"}.issubset(present):
        return (
            "LaunchServices contains stale registrations that point at missing app paths; review the generated "
            "LaunchServices report before any manual cleanup or app reinstall."
        )
    if "LS-E003" in present:
        return (
            "LaunchServices has duplicate bundle identifiers; compare the duplicate paths and versions before "
            "choosing a manual app action."
        )
    if "LS-E004" in present:
        return (
            "LaunchServices candidate cache files are present, but no stronger stale-registration evidence was "
            "found; collect a support bundle before proposing cleanup."
        )
    if rule_matches:
        return "LaunchServices rules matched, but the safest next step remains read-only report review."
    return "No focused LaunchServices repair evidence was found; keep the investigation read-only and collect a bundle if support needs artifacts."


LAUNCHSERVICES_MODULE = DiagnosticModule(
    id="launchservices",
    command_name="launchservices",
    evidence_provider=launchservices_evidence_provider,
    rules=LAUNCHSERVICES_RULES,
    repair_candidates=launchservices_repair_candidates,
    diagnosis_builder=launchservices_diagnosis_builder,
    fallback_repair_order=("collect-launchservices-support-bundle",),
    supporting_commands=LAUNCHSERVICES_SUPPORTING_COMMANDS,
)
