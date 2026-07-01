from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation
from macos_state_explorer.launchservices.parser import parse_lsdump


def block(*lines: str) -> str:
    return "\n".join(lines)


def test_parse_active_record(tmp_path: Path):
    app_path = tmp_path / "Google Chrome.app"
    app_path.mkdir()
    dump = block(
        "bundle id:                  Google Chrome (0x2a)",
        "sequenceNumber:             42",
        "path:                       " + str(app_path) + " (0x1c9c)",
        "identifier:                 com.google.Chrome",
        "name:                       Google Chrome",
        "displayName:                Chrome",
        "versionString:              1.2.3",
        "displayVersion:             1.2",
        "teamID:                     EQHXZ8M8AV",
        "reg date:                   2026-01-02 03:04:05 +0000",
    )

    records = parse_lsdump(dump, terms=[])

    assert len(records) == 1
    record = records[0]
    assert record.classification == "ACTIVE"
    assert record.path_clean == str(app_path)
    assert record.path_exists is True
    assert record.volume == "/"
    assert record.volume_exists is True
    assert record.canonical_id == "com.google.Chrome"
    assert record.sequence_number == 42
    assert record.registration_date == "2026-01-02 03:04:05 +0000"


def test_parse_orphaned_record(tmp_path: Path):
    missing_path = tmp_path / "Google Chrome Helper.app"
    dump = block(
        "bundle id:                  Chrome Helper (0xcd4)",
        "Bundle node not found on disk: Error",
        "path:                       " + str(missing_path) + " (0x1c9c)",
        "identifier:                 com.google.Chrome.helper",
    )

    records = parse_lsdump(dump, terms=["chrome"])

    assert len(records) == 1
    assert records[0].node_not_found is True
    assert records[0].path_exists is False
    assert records[0].classification == "ORPHANED"


def test_parse_missing_volume_record():
    dump = block(
        "bundle id:                  External Browser",
        "path:                       /Volumes/DefinitelyMissingVolume/Browser.app (0x1c9c)",
        "identifier:                 com.example.browser",
    )

    records = parse_lsdump(dump, terms=[])

    assert len(records) == 1
    assert records[0].volume == "/Volumes/DefinitelyMissingVolume"
    assert records[0].volume_exists is False
    assert records[0].classification == "MISSING_VOLUME"


def test_parse_missing_fields():
    records = parse_lsdump("bundle id:                  Minimal App")

    assert len(records) == 1
    assert records[0].path is None
    assert records[0].path_exists is None
    assert records[0].classification == "UNKNOWN"
    assert records[0].canonical_id == "Minimal App"


def test_parse_multiple_records(tmp_path: Path):
    first = tmp_path / "Google Chrome.app"
    second = tmp_path / "Safari.app"
    first.mkdir()
    second.mkdir()
    dump = "\n--------------------------------------------------------------------------------\n".join(
        [
            block(
                "bundle id:                  Google Chrome",
                "path:                       " + str(first),
                "identifier:                 com.google.Chrome",
            ),
            block(
                "bundle id:                  Safari",
                "path:                       " + str(second),
                "identifier:                 com.apple.Safari",
            ),
        ]
    )

    records = parse_lsdump(dump, terms=[])

    assert [record.identifier for record in records] == ["com.google.Chrome", "com.apple.Safari"]
    assert [record.classification for record in records] == ["ACTIVE", "ACTIVE"]


def test_unknown_fields_retained():
    dump = block(
        "bundle id:                  Google Chrome",
        "identifier:                 com.google.Chrome",
        "customField:                custom value",
        "another unknown:            yes",
    )

    records = parse_lsdump(dump, terms=[])

    assert records[0].fields == {
        "customField": "custom value",
        "another unknown": "yes",
    }


def test_cli_launchservices_still_writes_outputs(monkeypatch, tmp_path: Path):
    def fake_collect(self):
        return Observation(
            collector="launchservices",
            started_at=1,
            ended_at=2,
            payload={
                "entry_count": 0,
                "classification_counts": {},
                "entries": [],
                "stale_entries": [],
            },
        )

    monkeypatch.setattr("macos_state_explorer.cli.LaunchServicesCollector.collect", fake_collect)
    result = CliRunner().invoke(app, ["launchservices", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "launchservices.json").exists()
    assert (tmp_path / "stale-launchservices.json").exists()
