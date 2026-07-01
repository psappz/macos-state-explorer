from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.analysis import (
    LaunchServicesRepairability,
    LaunchServicesRootCause,
    analyze_launchservices,
    render_launchservices_analysis,
)
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.reports.launchservices import build_launchservices_report, write_launchservices_support_bundle


def record(
    path: str,
    *,
    bundle_id: str = "com.google.Chrome",
    name: str = "Google Chrome",
    version: str | None = "120.0",
    executable: str | None = "Contents/MacOS/Google Chrome",
    path_exists: bool | None = False,
    volume: str | None = "/",
    volume_exists: bool | None = True,
    classification: LaunchServicesStatus = LaunchServicesStatus.STALE,
) -> LaunchServicesRecord:
    return LaunchServicesRecord(
        raw_block=f"path: {path}",
        bundle_id=bundle_id,
        name=name,
        display_name=name,
        version=version,
        executable=executable,
        path=path,
        path_clean=path,
        path_exists=path_exists,
        volume=volume,
        volume_exists=volume_exists,
        classification=classification,
    )


def analysis_records() -> list[LaunchServicesRecord]:
    return [
        record("/Users/patrick/.Trash/Google Chrome.app", path_exists=True),
        record("/Applications/Missing.app", bundle_id="com.example.Missing", name="Missing", path_exists=False),
        record("/Volumes/Chrome/Google Chrome.app", volume="/Volumes/Chrome", volume_exists=True),
        record("/Volumes/OldDisk/Google Chrome.app", volume="/Volumes/OldDisk", volume_exists=False, classification=LaunchServicesStatus.MISSING_VOLUME),
        record("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/119.0", bundle_id="com.google.Chrome.framework", name="Google Chrome Framework", version="119.0"),
        record("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/120.0", bundle_id="com.google.Chrome.framework", name="Google Chrome Framework", version="120.0", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/118.0", bundle_id="com.google.Chrome.framework", name="Google Chrome Framework", version="118.0"),
        record("/Applications/Google Chrome.app/Contents/Helpers/Google Chrome Helper.app", bundle_id="com.google.Chrome.helper", name="Google Chrome Helper"),
        record("/Applications/Google Chrome old.app", version="119.0"),
        record("/Applications/Google Chrome.app", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Applications/Google Chrome Copy.app", path_exists=True, classification=LaunchServicesStatus.DUPLICATE),
        record("/tmp/Broken", bundle_id="com.example.Broken", name="Broken", executable=None),
        record("relative/no/path", bundle_id="com.example.Unknown", name="Unknown", path_exists=None, volume=None, volume_exists=None, classification=LaunchServicesStatus.UNKNOWN),
    ]


def snapshot(records: list[LaunchServicesRecord] | None = None) -> Snapshot:
    records = records or analysis_records()
    return Snapshot(
        host="ls-host",
        created_at=123.0,
        observations=[
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "entries": [item.model_dump(mode="python") for item in records],
                    "stale_entries": [
                        item.model_dump(mode="python")
                        for item in records
                        if item.classification in {LaunchServicesStatus.STALE, LaunchServicesStatus.ORPHANED, LaunchServicesStatus.MISSING_VOLUME, LaunchServicesStatus.DUPLICATE, LaunchServicesStatus.UNKNOWN}
                    ],
                },
            )
        ],
    )


def test_launchservices_analyzer_classifies_root_causes_and_repairability():
    analysis = analyze_launchservices(analysis_records())

    by_path = {entry.path: entry for entry in analysis.entries}
    assert by_path["/Users/patrick/.Trash/Google Chrome.app"].root_cause == LaunchServicesRootCause.TRASH_APPLICATION
    assert by_path["/Users/patrick/.Trash/Google Chrome.app"].repairability == LaunchServicesRepairability.SAFE_MANUAL
    assert by_path["/Applications/Missing.app"].root_cause == LaunchServicesRootCause.MISSING_APPLICATION_BUNDLE
    assert by_path["/Applications/Missing.app"].repairability == LaunchServicesRepairability.REQUIRES_REINSTALL
    assert by_path["/Volumes/Chrome/Google Chrome.app"].root_cause == LaunchServicesRootCause.MOUNTED_INSTALLER_DMG
    assert by_path["/Volumes/OldDisk/Google Chrome.app"].root_cause == LaunchServicesRootCause.NONEXISTENT_VOLUME
    assert by_path["/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/119.0"].root_cause == LaunchServicesRootCause.OLD_FRAMEWORK_VERSION
    assert by_path["/Applications/Google Chrome.app/Contents/Helpers/Google Chrome Helper.app"].root_cause == LaunchServicesRootCause.OLD_HELPER_APPLICATION
    assert by_path["/Applications/Google Chrome old.app"].root_cause == LaunchServicesRootCause.OLD_CHROME_VERSION
    assert by_path["/Applications/Google Chrome Copy.app"].root_cause == LaunchServicesRootCause.DUPLICATE_BUNDLE_REGISTRATION
    assert by_path["/tmp/Broken"].root_cause == LaunchServicesRootCause.INVALID_BUNDLE
    assert by_path["relative/no/path"].root_cause == LaunchServicesRootCause.UNKNOWN
    assert "Bundle resides inside ~/.Trash." in by_path["/Users/patrick/.Trash/Google Chrome.app"].evidence


def test_launchservices_analyzer_groups_deterministically_with_json_contract():
    analysis = analyze_launchservices(analysis_records())
    payload = analysis.to_json_dict()

    assert list(payload) == ["command", "entry_count", "groups", "entries"]
    assert [group["root_cause"] for group in payload["groups"]][:4] == [
        "Old framework version",
        "Duplicate bundle registration",
        "Invalid bundle",
        "Missing application bundle",
    ]
    framework_group = next(group for group in payload["groups"] if group["root_cause"] == "Old framework version")
    assert framework_group["count"] == 2
    assert list(framework_group) == ["root_cause", "count", "confidence", "explanation", "suggested_repair", "safety"]
    assert list(payload["entries"][0]) == [
        "path",
        "bundle_id",
        "bundle_name",
        "version",
        "executable",
        "exists_on_disk",
        "registration_source",
        "registration_type",
        "evidence",
        "root_cause",
        "repairability",
        "confidence",
    ]


def test_launchservices_analysis_human_rendering_contains_groups_and_entries():
    output = render_launchservices_analysis(analyze_launchservices(analysis_records()))

    assert output.startswith("LaunchServices root cause analysis")
    assert "Old framework version" in output
    assert "2 registrations" in output
    assert "Per-entry analysis" in output
    assert "/Users/patrick/.Trash/Google Chrome.app" in output
    assert "Repairability: SAFE_MANUAL" in output


def test_launchservices_analyze_cli_json_and_human(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot())
    runner = CliRunner()

    json_result = runner.invoke(app, ["launchservices", "analyze", "--json"])
    human_result = runner.invoke(app, ["launchservices", "analyze"])

    assert json_result.exit_code == 0
    assert json.loads(json_result.stdout)["command"] == "launchservices analyze"
    assert human_result.exit_code == 0
    assert human_result.stdout.startswith("LaunchServices root cause analysis")


def test_launchservices_report_and_bundle_include_analysis():
    report = build_launchservices_report(snapshot())
    payload = report.to_json_dict()

    assert list(payload) == ["command", "solution", "analysis", "supporting_commands", "bundle_schema_version"]
    assert payload["analysis"]["entry_count"] == len(analysis_records())
    bundle = write_launchservices_support_bundle(report, snapshot_path := __import__("pathlib").Path(__file__).parent / "tmp-support-bundle-test")
    try:
        assert json.loads((bundle / "launchservices-analysis.json").read_text())["command"] == "launchservices analyze"
        assert "Root cause analysis" in (bundle / "report.txt").read_text()
    finally:
        import shutil
        shutil.rmtree(snapshot_path, ignore_errors=True)


def test_local_network_evidence_summarizes_launchservices_root_causes():
    from macos_state_explorer.diagnostics.local_network.evidence import collect_local_network_evidence

    evidence = collect_local_network_evidence(snapshot())
    stale = next(item for item in evidence if item.id == "LN-E002")

    assert stale.present is True
    assert "stale LaunchServices registrations" in stale.detail
    assert "Root causes" in stale.detail
    assert "obsolete Chrome Framework" in stale.detail


def test_system_frameworks_and_appex_are_healthy_not_old_chrome_frameworks():
    records = [
        record(
            "/System/Library/ExtensionKit/Extensions/SecurityPrivacyExtension.appex",
            bundle_id="com.apple.SecurityPrivacyExtension",
            name="SecurityPrivacyExtension",
            version="1.0",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/System/Library/PrivateFrameworks/ShareKit.framework/Versions/A/PlugIns/ShareSheet.appex",
            bundle_id="com.apple.ShareKit.ShareSheet",
            name="ShareSheet",
            version="1.0",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/System/Library/PrivateFrameworks/WorkflowKit.framework",
            bundle_id="com.apple.WorkflowKit",
            name="WorkflowKit",
            version="1.0",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
    ]

    analysis = analyze_launchservices(records)

    assert {entry.root_cause for entry in analysis.entries} == {LaunchServicesRootCause.HEALTHY}
    assert all("Chrome Framework version" not in " ".join(entry.evidence) for entry in analysis.entries)
    assert all(group.root_cause != LaunchServicesRootCause.OLD_FRAMEWORK_VERSION for group in analysis.groups)


def test_old_framework_version_only_applies_to_google_chrome_framework_paths():
    analysis = analyze_launchservices(
        [
            record(
                "/System/Library/PrivateFrameworks/ShareKit.framework/Versions/A/ShareKit",
                bundle_id="com.apple.ShareKit",
                name="ShareKit",
                version="1.0",
                path_exists=False,
                classification=LaunchServicesStatus.STALE,
            ),
            record(
                "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.0.0",
                bundle_id="com.google.Chrome.framework",
                name="Google Chrome Framework",
                version="148.0.0.0",
                path_exists=False,
                classification=LaunchServicesStatus.STALE,
            ),
            record(
                "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/149.0.0.0",
                bundle_id="com.google.Chrome.framework",
                name="Google Chrome Framework",
                version="149.0.0.0",
                path_exists=True,
                classification=LaunchServicesStatus.ACTIVE,
            ),
        ]
    )
    by_path = {entry.path: entry for entry in analysis.entries}

    assert by_path["/System/Library/PrivateFrameworks/ShareKit.framework/Versions/A/ShareKit"].root_cause != LaunchServicesRootCause.OLD_FRAMEWORK_VERSION
    assert by_path["/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.0.0"].root_cause == LaunchServicesRootCause.OLD_FRAMEWORK_VERSION


def test_healthy_entries_do_not_dominate_summary_or_default_human_output():
    analysis = analyze_launchservices(
        [
            record("/Applications/Safari.app", bundle_id="com.apple.Safari", name="Safari", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
            record("/Applications/Notes.app", bundle_id="com.apple.Notes", name="Notes", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
            record("/Users/patrick/.Trash/Google Chrome.app", path_exists=True),
        ]
    )
    payload = analysis.to_json_dict()
    output = render_launchservices_analysis(analysis)

    assert [group["root_cause"] for group in payload["groups"]] == ["Trash application"]
    assert [entry["root_cause"] for entry in payload["entries"]].count("Healthy") == 2
    assert "/Applications/Safari.app" not in output
    assert "/Users/patrick/.Trash/Google Chrome.app" in output


def test_real_run_examples_cover_volumes_trash_and_healthy_apps():
    analysis = analyze_launchservices(
        [
            record("/Volumes/Google Chrome/Google Chrome.app", volume="/Volumes/Google Chrome", volume_exists=False, classification=LaunchServicesStatus.MISSING_VOLUME),
            record("/Users/patrick/.Trash/Google Chrome.app", path_exists=True),
            record("/Applications/Firefox.app", bundle_id="org.mozilla.firefox", name="Firefox", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        ]
    )
    by_path = {entry.path: entry for entry in analysis.entries}

    assert by_path["/Volumes/Google Chrome/Google Chrome.app"].root_cause == LaunchServicesRootCause.NONEXISTENT_VOLUME
    assert by_path["/Users/patrick/.Trash/Google Chrome.app"].root_cause == LaunchServicesRootCause.TRASH_APPLICATION
    assert by_path["/Applications/Firefox.app"].root_cause == LaunchServicesRootCause.HEALTHY
