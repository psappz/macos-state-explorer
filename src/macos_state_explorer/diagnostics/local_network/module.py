from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence, cast

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import (
    CommandRunner,
    DiagnosticEvidence,
    DiagnosticModule,
    RepairAction,
    RepairCandidate,
    RepairCommand,
    RepairPrecondition,
    RepairPreflightResult,
    RepairRollback,
    RepairSafety,
)
from macos_state_explorer.diagnostics.local_network.evidence import collect_local_network_evidence
from macos_state_explorer.diagnostics.local_network.rules import LOCAL_NETWORK_RULES
from macos_state_explorer.diagnostics.rules import RuleMatch

LOCAL_NETWORK_SUPPORTING_COMMANDS = (
    "mse diagnose local-network",
    "mse launchservices ~/Desktop/mse-launchservices",
    "mse trace local-network --out ~/Desktop/mse-local-network-trace",
    "mse collect ~/Desktop/mse-local-network-collect --fast",
)


def local_network_evidence_provider(
    snapshot: Snapshot,
    context: dict[str, Any] | None = None,
) -> list[DiagnosticEvidence]:
    context = context or {}
    trace_analysis = context.get("trace_analysis")
    return collect_local_network_evidence(
        snapshot,
        trace_analysis=trace_analysis if isinstance(trace_analysis, dict) else None,
    )


def local_network_repair_candidates(
    evidence: Sequence[DiagnosticEvidence],
    context: dict[str, Any] | None = None,
) -> dict[str, RepairCandidate]:
    evidence_by_id = {item.id: item for item in evidence}

    def present(evidence_id: str) -> bool:
        item = evidence_by_id.get(evidence_id)
        return bool(item and item.present)

    def present_ids(*evidence_ids: str) -> list[str]:
        return [evidence_id for evidence_id in evidence_ids if present(evidence_id)]

    trash_evidence = present_ids("LN-E002", "LN-E003", "LN-E006", "LN-E007") or ["LN-E007"]
    reinstall_evidence = present_ids("LN-E001", "LN-E002", "LN-E005", "LN-E006", "LN-E008") or ["LN-E001"]
    trace_evidence = present_ids("LN-E001", "LN-E004", "LN-E005", "LN-E009") or ["LN-E001"]

    return {
        "manual-empty-trash-reboot": RepairCandidate(
            id="manual-empty-trash-reboot",
            title="Empty Trash manually, then reboot and re-check Local Network",
            risk="Medium: Emptying Trash permanently removes items already placed there; the tool does not do this automatically.",
            manual_action="Review Trash in Finder yourself. If it only contains disposable Chrome/Google leftovers, empty it from Finder, reboot macOS, open Local Network, then rerun verification.",
            expected_result="LaunchServices should stop resolving trashed or orphaned Chrome registrations; the Local Network list should drop stale Chrome/Google entries if they came from trashed app bundles.",
            verification_command="mse diagnose local-network",
            fallback_branch="If Chrome/Google Local Network entries remain, continue with branch 2: manual Chrome reinstall.",
            evidence_ids=trash_evidence,
            action_id=None,
        ),
        "manual-reinstall-chrome": RepairCandidate(
            id="manual-reinstall-chrome",
            title="Manually reinstall Google Chrome from a fresh download",
            risk="Low to medium: user-driven app reinstall; bookmarks/profile data should remain in the Chrome profile, but the tool will not remove or edit any files.",
            manual_action="Quit Chrome normally, download Chrome from Google, install it into /Applications, reboot, and open Chrome once. Do not use this tool to remove app bundles or profiles.",
            expected_result="A fresh signed /Applications registration should replace code-sign-clone or orphaned LaunchServices records as the active Chrome identity.",
            verification_command="mse diagnose local-network",
            fallback_branch="If Local Network still shows the same broken Chrome state, continue with branch 3: capture a focused trace.",
            evidence_ids=reinstall_evidence,
            action_id="refresh-launchservices-user-cache",
        ),
        "trace-local-network": RepairCandidate(
            id="trace-local-network",
            title="Run a focused Local Network trace while opening System Settings",
            risk="Low: read-only logging and filesystem observation; sudo may be requested by macOS for fs_usage/lsof visibility.",
            manual_action="Run the trace command, open System Settings → Privacy & Security → Local Network, wait 20–30 seconds, then stop the trace.",
            expected_result="The trace should identify whether SecurityPrivacyExtension, LaunchServices .csstore reads, TCC/REG, or another privacy cache is feeding the stale GUI entry.",
            verification_command="mse trace local-network --out ~/Desktop/mse-local-network-trace",
            fallback_branch="If the trace still does not identify a safe repair, collect a full read-only bundle with mse collect and inspect the generated evidence before proposing any higher-risk action.",
            evidence_ids=trace_evidence,
            action_id="open-local-network-settings",
        ),
    }


def local_network_diagnosis_builder(
    evidence: Sequence[DiagnosticEvidence],
    rule_matches: Sequence[RuleMatch],
    repair_plan: Sequence[RepairCandidate],
    context: dict[str, Any] | None = None,
) -> str:
    evidence_by_id = {item.id: item for item in evidence}

    def present(evidence_id: str) -> bool:
        item = evidence_by_id.get(evidence_id)
        return bool(item and item.present)

    if present("LN-E007"):
        return (
            "The strongest evidence is a Chrome/Google LaunchServices identity in Trash; empty Trash is only "
            "ranked first because Trash evidence is present."
        )
    if present("LN-E006"):
        return (
            "Trace or LaunchServices evidence shows a Chrome code-sign-clone identity, so a manual Chrome reinstall "
            "is ranked before another trace capture."
        )
    if present("LN-E002") or present("LN-E008"):
        return (
            "TCC does not currently prove a Local Network permission row problem; the strongest branch is stale "
            "Chrome/Google identity data in LaunchServices that is not specifically tied to Trash, so reinstall is safer than emptying Trash."
        )
    if present("LN-E004") or present("LN-E005") or present("LN-E009"):
        return (
            "The fast snapshot lacks strong LaunchServices repair evidence, but trace signals implicate the Local Network privacy UI path; "
            "capture or inspect trace evidence before proposing manual app changes."
        )
    if rule_matches:
        return "Local Network diagnostic rules matched, but none require a manual repair before additional read-only trace evidence."
    return (
        "The current read-only snapshot does not contain enough stale LaunchServices evidence to repair safely; "
        "start with trace evidence before any manual repair beyond normal reboot/re-check."
    )


def _fallback_detail(evidence: Sequence[DiagnosticEvidence]) -> str:
    if evidence:
        return "Retry trace collection and compare evidence IDs before escalating to manual reinstall."
    return (
        "The current read-only snapshot does not contain enough stale LaunchServices evidence to repair safely; "
        "start with trace evidence before any manual repair beyond normal reboot/re-check."
    )


def _lsregister_refresh_preflight(lsregister: Path, refresh_command: RepairCommand):
    def preflight(_runner: CommandRunner) -> RepairPreflightResult:
        expected_argv = (str(lsregister), "-r", "-f", "-apps", "user")
        forbidden_options = {"-kill", "-delete", "-u"}
        used_forbidden_options = tuple(option for option in refresh_command.argv if option in forbidden_options)
        if refresh_command.argv != expected_argv or used_forbidden_options:
            return RepairPreflightResult(
                supported=False,
                message="Unsafe or unsupported lsregister refresh command form.",
                errors=(
                    "The LaunchServices repair action must use exactly "
                    "`lsregister -r -f -apps user` and must not use destructive or removed options "
                    f"{', '.join(used_forbidden_options) or 'none'}.",
                ),
            )
        return RepairPreflightResult(
            supported=True,
            message="lsregister refresh command form is safe to attempt.",
        )

    return preflight


def local_network_repair_actions(
    evidence: Sequence[DiagnosticEvidence],
    candidates: dict[str, RepairCandidate],
    context: dict[str, Any] | None = None,
) -> dict[str, RepairAction]:
    context = context or {}
    runner = context.get("command_runner")
    command_runner = cast(CommandRunner, runner) if callable(runner) else None
    lsregister = Path(
        "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    )
    refresh_command = RepairCommand(
        argv=(str(lsregister), "-r", "-f", "-apps", "user"),
        description="Refresh user-domain application registrations without deleting the LaunchServices database.",
    )
    return {
        "refresh-launchservices-user-cache": RepairAction(
            id="refresh-launchservices-user-cache",
            title="Refresh the user LaunchServices cache",
            description="Regenerate the per-user LaunchServices derived cache from installed application registrations.",
            safety=RepairSafety.MODERATE,
            why_safe=(
                "This is limited to the user-domain LaunchServices derived cache; it does not delete applications, "
                "profiles, TCC databases, or user documents, and macOS can rebuild the cache deterministically."
            ),
            commands=(refresh_command,),
            preconditions=(
                RepairPrecondition(
                    id="lsregister-present",
                    title="lsregister helper exists",
                    satisfied=lsregister.exists(),
                    detail=str(lsregister),
                ),
            ),
            rollback=RepairRollback(
                available=False,
                description="No rollback is needed for a derived cache refresh; macOS rebuilds LaunchServices registrations from installed apps.",
                metadata={"scope": "user-domain-derived-cache"},
            ),
            files_touched=(
                "~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist",
                "~/Library/Application Support/com.apple.sharedfilelist",
            ),
            runner=command_runner,
            preflight=_lsregister_refresh_preflight(lsregister, refresh_command),
        ),
        "open-local-network-settings": RepairAction(
            id="open-local-network-settings",
            title="Open Local Network privacy settings",
            description="Open the System Settings Local Network privacy pane for user-guided inspection.",
            safety=RepairSafety.INTERACTIVE,
            why_safe="Opening System Settings is interactive and read-only until the user changes a toggle manually.",
            commands=(
                RepairCommand(
                    argv=("open", "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"),
                    description="Open System Settings → Privacy & Security → Local Network.",
                ),
            ),
            preconditions=(
                RepairPrecondition(
                    id="macos-open-command",
                    title="macOS open command is available",
                    satisfied=Path("/usr/bin/open").exists(),
                    detail="/usr/bin/open",
                ),
            ),
            rollback=RepairRollback(
                available=True,
                description="Close the opened System Settings window without changing any toggles.",
                metadata={"user_interaction_required": True},
            ),
            files_touched=(),
            runner=command_runner,
        ),
    }


LOCAL_NETWORK_MODULE = DiagnosticModule(
    id="local-network",
    command_name="local-network",
    evidence_provider=local_network_evidence_provider,
    rules=LOCAL_NETWORK_RULES,
    repair_candidates=local_network_repair_candidates,
    diagnosis_builder=local_network_diagnosis_builder,
    repair_actions=local_network_repair_actions,
    fallback_repair_order=("trace-local-network",),
    supporting_commands=LOCAL_NETWORK_SUPPORTING_COMMANDS,
)
