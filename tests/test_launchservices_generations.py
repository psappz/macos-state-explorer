from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.generations import (
    GenerationClassification,
    analyze_generations,
    render_generation_summary,
)
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


def record(
    path: str,
    *,
    bundle_id: str,
    name: str,
    version: str | None,
    executable: str | None = "Contents/MacOS/App",
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
        display_version=version,
        executable=executable,
        path=path,
        path_clean=path,
        path_exists=path_exists,
        volume=volume,
        volume_exists=volume_exists,
        classification=classification,
    )


def chrome_generation_records() -> list[LaunchServicesRecord]:
    return [
        record(
            "/Applications/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.250",
            path_exists=True,
            classification=LaunchServicesStatus.ACTIVE,
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper",
            name="Google Chrome Helper",
            version="148.0.7778.216",
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216/Helpers/Google Chrome Helper Alerts.app",
            bundle_id="com.google.Chrome.helper.alerts",
            name="Google Chrome Helper Alerts",
            version="148.0.7778.216",
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/149.0.7827.54/Helpers/Google Chrome Helper.app",
            bundle_id="com.google.Chrome.helper",
            name="Google Chrome Helper",
            version="149.0.7827.54",
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/149.0.7827.54/Helpers/Google Chrome Helper Alerts.app",
            bundle_id="com.google.Chrome.helper.alerts",
            name="Google Chrome Helper Alerts",
            version="149.0.7827.54",
        ),
        record(
            "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Framework.framework/Versions/148.0.7778.216",
            bundle_id="com.google.Chrome.framework",
            name="Google Chrome Framework",
            version="148.0.7778.216",
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=True,
            classification=LaunchServicesStatus.STALE,
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app/Contents/Helpers/Google Chrome Helper (Renderer).app",
            bundle_id="com.google.Chrome.helper.renderer",
            name="Google Chrome Helper (Renderer)",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=True,
        ),
        record(
            "/Volumes/Google Chrome/Google Chrome.app/Contents/Helpers/Google Chrome Helper (GPU).app",
            bundle_id="com.google.Chrome.helper.gpu",
            name="Google Chrome Helper (GPU)",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=True,
        ),
        record(
            "/Volumes/Google Chrome/GoogleUpdater.app",
            bundle_id="com.google.GoogleUpdater",
            name="GoogleUpdater",
            version="149.0.7827.201",
            volume="/Volumes/Google Chrome",
            volume_exists=True,
        ),
        record(
            "/Users/patrick/.Trash/Google Chrome.app",
            bundle_id="com.google.Chrome",
            name="Google Chrome",
            version="149.0.7827.201",
            path_exists=True,
        ),
    ]


def family_records() -> list[LaunchServicesRecord]:
    return [
        record("/Applications/Microsoft Edge.app", bundle_id="com.microsoft.edgemac", name="Microsoft Edge", version="125.1", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Applications/Microsoft Edge.app/Contents/Frameworks/Microsoft Edge Framework.framework/Versions/124.9", bundle_id="com.microsoft.Edge.framework", name="Microsoft Edge Framework", version="124.9"),
        record("/Applications/Chromium.app", bundle_id="org.chromium.Chromium", name="Chromium", version="130.0", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Applications/Brave Browser.app", bundle_id="com.brave.Browser", name="Brave Browser", version="1.70", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
        record("/Applications/Arc.app", bundle_id="company.thebrowser.Browser", name="Arc", version="1.60", path_exists=True, classification=LaunchServicesStatus.ACTIVE),
    ]


def snapshot(records: list[LaunchServicesRecord]) -> Snapshot:
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
                        if item.classification != LaunchServicesStatus.ACTIVE
                    ],
                },
            )
        ],
    )


def test_generation_analyzer_groups_chrome_helpers_framework_updater_volume_and_trash():
    analysis = analyze_generations(chrome_generation_records())
    by_id = {generation.generation_id: generation for generation in analysis.generations}

    assert by_id["google-chrome:149.0.7827.250:applications-google-chrome-app"].classification == GenerationClassification.ACTIVE
    assert by_id["google-chrome:148.0.7778.216:applications-google-chrome-app"].classification == GenerationClassification.STALE
    assert len(by_id["google-chrome:148.0.7778.216:applications-google-chrome-app"].helper_registrations) == 2
    assert len(by_id["google-chrome:148.0.7778.216:applications-google-chrome-app"].framework_registrations) == 1
    assert by_id["google-chrome:149.0.7827.201:volumes-google-chrome-google-chrome-app"].classification == GenerationClassification.MOUNTED_INSTALLER
    assert len(by_id["google-chrome:149.0.7827.201:volumes-google-chrome-google-chrome-app"].updater_registrations) == 1
    assert by_id["google-chrome:149.0.7827.201:users-patrick-trash-google-chrome-app"].classification == GenerationClassification.TRASH
    assert sorted(reg.generation_id for reg in analysis.registrations) == sorted([reg.generation_id for gen in analysis.generations for reg in gen.registrations])


def test_generation_analyzer_supports_chromium_family_products():
    analysis = analyze_generations(family_records())
    families = {(generation.product_family, generation.vendor) for generation in analysis.generations}

    assert ("Google Chrome", "Google") not in families
    assert ("Microsoft Edge", "Microsoft") in families
    assert ("Chromium", "Chromium") in families
    assert ("Brave", "Brave") in families
    assert ("Arc", "The Browser Company") in families


def test_generation_json_schema_is_deterministic_and_entries_reference_one_generation():
    payload = analyze_generations(chrome_generation_records()).to_json_dict()

    assert list(payload) == ["command", "generation_count", "generations", "registrations", "summary"]
    assert list(payload["generations"][0]) == [
        "product_family",
        "vendor",
        "bundle_identifier",
        "generation_id",
        "version",
        "installation_root",
        "classification",
        "exists",
        "active",
        "stale",
        "confidence",
        "registration_count",
        "helper_registration_count",
        "framework_registration_count",
        "updater_registration_count",
        "mounted_volume_registration_count",
        "trash_registration_count",
        "registrations",
    ]
    assert all(reg["generation_id"] for reg in payload["registrations"])
    assert {item["classification"] for item in payload["generations"]} >= {"ACTIVE", "STALE", "MOUNTED_INSTALLER", "TRASH"}


def test_generation_human_summary_prioritizes_active_old_mounted_and_trash():
    output = render_generation_summary(analyze_generations(chrome_generation_records()))

    assert output.startswith("LaunchServices generation analysis")
    assert "Google Chrome" in output
    assert "Active generation" in output
    assert "149.0.7827.250" in output
    assert "Older generations" in output
    assert "148.0.7778.216" in output
    assert "Mounted installer" in output
    assert "149.0.7827.201" in output
    assert "Trash" in output


def test_launchservices_generations_cli_json_and_human(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(chrome_generation_records()))
    runner = CliRunner()

    json_result = runner.invoke(app, ["launchservices", "generations", "--json"])
    human_result = runner.invoke(app, ["launchservices", "generations"])

    assert json_result.exit_code == 0
    assert json.loads(json_result.stdout)["command"] == "launchservices generations"
    assert human_result.exit_code == 0
    assert "LaunchServices generation analysis" in human_result.stdout


def test_launchservices_analyze_json_adds_generation_summary_without_breaking_prefix(monkeypatch):
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snapshot(chrome_generation_records()))
    result = CliRunner().invoke(app, ["launchservices", "analyze", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload)[:4] == ["command", "entry_count", "groups", "entries"]
    assert payload["generation_summary"]["obsolete_generation_count"] == 2
    assert payload["generation_summary"]["mounted_installer_generation_count"] == 1
    assert payload["generation_summary"]["trash_generation_count"] == 1


def test_local_network_evidence_summarizes_obsolete_chrome_generations():
    from macos_state_explorer.diagnostics.local_network.evidence import collect_local_network_evidence

    evidence = collect_local_network_evidence(snapshot(chrome_generation_records()))
    stale = next(item for item in evidence if item.id == "LN-E002")

    assert stale.present is True
    assert "Chrome" in stale.detail
    assert "2 obsolete generations" in stale.detail
    assert "1 mounted installer generation" in stale.detail
    assert "1 Trash generation" in stale.detail
