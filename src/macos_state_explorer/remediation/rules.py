from __future__ import annotations

from macos_state_explorer.evidence.models import EvidenceSet
from macos_state_explorer.remediation.models import RemediationAction, RemediationPlan


def build_remediation_plan(evidence: EvidenceSet) -> RemediationPlan:
    actions: list[RemediationAction] = []
    evidence_by_id = {item.id: item for item in evidence.items}

    orphaned = evidence_by_id.get("launchservices.orphaned_registrations")
    if orphaned and _mentions_chrome_or_google(orphaned.data):
        actions.extend(_chrome_orphaned_actions(orphaned.id))

    tcc = evidence_by_id.get("tcc.no_localnetwork_rows")
    if tcc:
        actions.extend(_localnetwork_prompt_actions(tcc.id))

    stale_ids = [
        item_id
        for item_id in (
            "launchservices.orphaned_registrations",
            "launchservices.missing_volume_registrations",
            "launchservices.stale_app_paths",
            "launchservices.duplicate_bundle_registrations",
        )
        if item_id in evidence_by_id
    ]
    if stale_ids:
        actions.extend(_launchservices_stale_actions(stale_ids))

    summary = (
        f"{len(actions)} safe recommended actions generated from {len(evidence.items)} evidence items."
        if actions
        else "No remediation actions are recommended from the current evidence."
    )
    return RemediationPlan(
        title="Safe remediation plan",
        summary=summary,
        actions=actions,
    )


def _chrome_orphaned_actions(evidence_id: str) -> list[RemediationAction]:
    return [
        RemediationAction(
            id="chrome.empty_trash_if_present",
            title="Empty Trash manually if Chrome is there",
            description=(
                "If Google Chrome or Chrome Helper is in Trash, empty Trash from Finder after confirming you no "
                "longer need those files. The tool will not delete files for you."
            ),
            risk="medium",
            mode="manual",
            commands=[],
            requires_confirmation=True,
            evidence_ids=[evidence_id],
        ),
        RemediationAction(
            id="chrome.reboot",
            title="Reboot macOS",
            description="Restart macOS so LaunchServices and privacy-related UI state can reload naturally.",
            risk="low",
            mode="manual",
            commands=[],
            requires_confirmation=True,
            evidence_ids=[evidence_id],
        ),
        RemediationAction(
            id="chrome.reinstall_cleanly_if_needed",
            title="Reinstall Chrome cleanly if needed",
            description="If Chrome is still missing or inconsistent after reboot, reinstall Chrome from the official installer.",
            risk="medium",
            mode="manual",
            commands=[],
            requires_confirmation=True,
            evidence_ids=[evidence_id],
        ),
        RemediationAction(
            id="chrome.rerun_launchservices",
            title="Rerun LaunchServices collection",
            description="Regenerate LaunchServices evidence after manual remediation.",
            risk="low",
            mode="read-only",
            commands=["mse launchservices ~/Desktop/mse-ls"],
            requires_confirmation=False,
            evidence_ids=[evidence_id],
        ),
        RemediationAction(
            id="chrome.rerun_collect",
            title="Rerun full collection",
            description="Regenerate the full report after manual remediation.",
            risk="low",
            mode="read-only",
            commands=["mse collect ~/Desktop/mse-report"],
            requires_confirmation=False,
            evidence_ids=[evidence_id],
        ),
    ]


def _localnetwork_prompt_actions(evidence_id: str) -> list[RemediationAction]:
    return [
        RemediationAction(
            id="localnetwork.trigger_prompt",
            title="Trigger the Local Network permission prompt",
            description=(
                "Launch the app and perform an action that accesses the local network. This should cause macOS "
                "to present the permission prompt when appropriate."
            ),
            risk="low",
            mode="manual",
            commands=[],
            requires_confirmation=True,
            evidence_ids=[evidence_id],
        ),
        RemediationAction(
            id="localnetwork.verify_settings",
            title="Verify System Settings",
            description="Open System Settings and review Privacy & Security > Local Network for the app.",
            risk="low",
            mode="manual",
            commands=[],
            requires_confirmation=True,
            evidence_ids=[evidence_id],
        ),
        RemediationAction(
            id="localnetwork.rerun_tcc_collector",
            title="Rerun the TCC collector",
            description="Rerun a read-only collection to verify whether Local Network rows appear after the prompt.",
            risk="low",
            mode="read-only",
            commands=["mse collect ~/Desktop/mse-tcc-check --fast"],
            requires_confirmation=False,
            evidence_ids=[evidence_id],
        ),
    ]


def _launchservices_stale_actions(evidence_ids: list[str]) -> list[RemediationAction]:
    return [
        RemediationAction(
            id="launchservices.do_not_edit_databases",
            title="Do not edit LaunchServices databases manually",
            description=(
                "Direct database edits are unsafe and unsupported. Prefer normal macOS lifecycle actions such "
                "as rebooting and reinstalling affected apps."
            ),
            risk="high",
            mode="unsafe-warning",
            commands=[],
            requires_confirmation=True,
            evidence_ids=evidence_ids,
        ),
        RemediationAction(
            id="launchservices.prefer_reboot_reinstall",
            title="Prefer reboot and app reinstall",
            description="Use reboot and clean app reinstall as the safe path for stale LaunchServices registrations.",
            risk="low",
            mode="manual",
            commands=[],
            requires_confirmation=True,
            evidence_ids=evidence_ids,
        ),
        RemediationAction(
            id="launchservices.document_lsregister_behavior",
            title="Document lsregister behavior",
            description="Record before/after LaunchServices output so stale registration behavior can be explained safely.",
            risk="low",
            mode="read-only",
            commands=["mse launchservices ~/Desktop/mse-ls-after"],
            requires_confirmation=False,
            evidence_ids=evidence_ids,
        ),
    ]


def _mentions_chrome_or_google(data: dict[str, object]) -> bool:
    return "chrome" in str(data).lower() or "google" in str(data).lower()
