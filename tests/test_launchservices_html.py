from __future__ import annotations

from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.reports.launchservices_html import render_launchservices_html


def record(
    bundle_id: str,
    *,
    version: str,
    path: str,
    classification: LaunchServicesStatus,
    volume: str = "/",
    volume_exists: bool | None = True,
) -> dict[str, object]:
    return LaunchServicesRecord(
        raw_block="raw",
        bundle_id=bundle_id,
        display_name="Example",
        version=version,
        path_clean=path,
        path_exists=classification == LaunchServicesStatus.ACTIVE,
        volume=volume,
        volume_exists=volume_exists,
        registration_date="2026-01-01 00:00:00 +0000",
        classification=classification,
    ).model_dump(mode="python")


def test_render_launchservices_html_includes_explorer_controls_and_sections():
    html = render_launchservices_html(
        {
            "entries": [
                record(
                    "com.example.App",
                    version="1.0",
                    path="/Applications/Example.app",
                    classification=LaunchServicesStatus.ACTIVE,
                )
            ]
        }
    )

    assert "LaunchServices Explorer" in html
    assert 'type="search"' in html
    assert "<details" in html
    assert "<table" in html
    assert LaunchServicesStatus.ACTIVE.value in html
    assert "prefers-color-scheme: dark" in html


def test_render_launchservices_html_warns_about_duplicates_orphans_and_volumes():
    html = render_launchservices_html(
        {
            "entries": [
                record(
                    "com.example.App",
                    version="1.0",
                    path="/Applications/Example.app",
                    classification=LaunchServicesStatus.ACTIVE,
                ),
                record(
                    "com.example.App",
                    version="1.0",
                    path="/Volumes/Missing/Example.app",
                    classification=LaunchServicesStatus.ORPHANED,
                    volume="/Volumes/Missing",
                    volume_exists=False,
                ),
            ]
        }
    )

    assert "Duplicate bundle identifier" in html
    assert "Multiple registered paths" in html
    assert "Orphaned registration" in html
    assert "Missing volume" in html
