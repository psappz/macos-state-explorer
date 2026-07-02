from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle


def record(
    path: str,
    *,
    bundle_id: str,
    name: str,
    version: str | None,
    path_exists: bool | None = False,
    classification: LaunchServicesStatus = LaunchServicesStatus.STALE,
) -> LaunchServicesRecord:
    return LaunchServicesRecord(
        raw_block=f"path: {path}",
        bundle_id=bundle_id,
        identifier=bundle_id,
        canonical_id=bundle_id,
        name=name,
        display_name=name,
        version=version,
        display_version=version,
        path=path,
        path_clean=path,
        path_exists=path_exists,
        volume="/",
        volume_exists=True,
        classification=classification,
    )


def regeneration_records() -> list[LaunchServicesRecord]:
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
            path_exists=False,
        ),
        record(
            "/Applications/GoogleUpdater.app/Contents/Helpers/GoogleUpdater Helper.app",
            bundle_id="com.google.GoogleUpdater.helper",
            name="GoogleUpdater Helper",
            version="1.0",
            path_exists=True,
        ),
    ]


def snapshot(records: list[LaunchServicesRecord] | None = None) -> Snapshot:
    records = records or regeneration_records()
    return Snapshot(
        host="regeneration-host",
        created_at=123.0,
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}},
            ),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={"entries": [item.model_dump(mode="python") for item in records]},
            ),
        ],
    )


def trace_analysis() -> dict[str, object]:
    csstore = "/private/var/folders/zz/com.apple.LaunchServices/com.apple.LaunchServices-3027.csstore"
    return {
        "created_at": 1.0,
        "signal_counts": {"launchservices_csstore": 2, "runningboard": 1, "securityprivacyextension": 1},
        "timeline_events": [],
        "normalized_events": [
            {
                "timestamp": "2026-07-02 15:08:22.100000",
                "process": "launchctl",
                "pid": 88,
                "operation": "read",
                "file_path": "/Library/LaunchAgents/com.google.GoogleUpdater.plist",
                "source": "launchctl",
                "source_file": "launchctl_loop.txt",
                "signal": "googleupdater_launchagent",
                "confidence": 0.9,
                "raw_reference": "launchctl com.google.GoogleUpdater",
            },
            {
                "timestamp": "2026-07-02 15:08:22.200000",
                "process": "GoogleUpdater",
                "pid": 4815,
                "operation": "launch",
                "file_path": "/Applications/GoogleUpdater.app",
                "source": "process",
                "source_file": "process_loop.txt",
                "signal": "googleupdater",
                "confidence": 0.92,
                "raw_reference": "GoogleUpdater.app launch",
            },
            {
                "timestamp": "2026-07-02 15:08:23.000000",
                "process": "lsd",
                "pid": 222,
                "operation": "cache rebuild",
                "file_path": csstore,
                "source": "fs_usage",
                "source_file": "fs_usage.txt",
                "signal": "launchservices_csstore",
                "confidence": 0.9,
                "raw_reference": f"lsd rebuild {csstore}",
            },
            {
                "timestamp": "2026-07-02 15:08:24.000000",
                "process": "SecurityPrivacyExtension",
                "pid": 333,
                "operation": "read",
                "file_path": csstore,
                "source": "fs_usage",
                "source_file": "fs_usage.txt",
                "signal": "launchservices_csstore",
                "confidence": 0.88,
                "raw_reference": f"SecurityPrivacyExtension read {csstore}",
            },
        ],
    }


def write_trace(path: Path) -> Path:
    path.mkdir()
    (path / "analysis.json").write_text(json.dumps(trace_analysis()))
    return path


def write_audit(path: Path, generation_id: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "event": "launchservices_execute_plan_run",
                "command": "launchservices execute-plan",
                "confirmed": True,
                "status": "MUTATED_BUT_REGENERATED",
                "final_verdict": "MUTATED_BUT_REGENERATED",
                "generation_diff": {"removed": [], "added": [], "persisted": [], "regenerated": [generation_id], "still_present": [generation_id]},
                "executed_steps": [{"generation_id": generation_id}],
            }
        )
        + "\n"
    )
    return path


def stale_generation_id(payload: dict[str, object]) -> str:
    generations = payload["generations"]
    assert isinstance(generations, list)
    return next(item["generation_id"] for item in generations if isinstance(item, dict) and item["product_family"] == "Google Chrome" and item["classification"] == "STALE")


def test_regeneration_json_classifies_regenerator_with_categorized_evidence(monkeypatch, tmp_path):
    snap = snapshot()
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)
    generations = json.loads(CliRunner().invoke(app, ["launchservices", "generations", "--json"]).stdout)
    generation_id = stale_generation_id(generations)
    trace = write_trace(tmp_path / "trace")
    audit = write_audit(tmp_path / "audit.jsonl", generation_id)

    result = CliRunner().invoke(app, ["launchservices", "regeneration", "--trace", str(trace), "--audit-log", str(audit), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert list(payload)[:6] == ["command", "regeneration_id", "timestamp", "generation_count", "summary", "generations"]
    assert payload["command"] == "launchservices regeneration"
    target = next(item for item in payload["generations"] if item["generation_id"] == generation_id)
    assert target["producer"] == "LaunchServices application enumeration"
    assert target["regenerator"] == "GoogleUpdater LaunchAgent"
    assert target["confidence"] >= 0.9
    assert target["evidence_categories"] == ["Observed", "Correlated", "Unknown"]
    assert any(item["category"] == "Observed" and item["source"] == "audit" for item in target["observed_evidence"])
    assert any(item["category"] == "Correlated" and "LaunchServices cache rebuild" in item["detail"] for item in target["correlated_evidence"])
    assert any(item["category"] == "Unknown" and item["label"] == "SecurityPrivacyExtension" for item in target["unknown_evidence"])


def test_regeneration_human_cli_and_deterministic_json(monkeypatch, tmp_path):
    snap = snapshot()
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)
    generations = json.loads(CliRunner().invoke(app, ["launchservices", "generations", "--json"]).stdout)
    generation_id = stale_generation_id(generations)
    trace = write_trace(tmp_path / "trace")
    audit = write_audit(tmp_path / "audit.jsonl", generation_id)

    human = CliRunner().invoke(app, ["launchservices", "regeneration", "--trace", str(trace), "--audit-log", str(audit)])
    first = CliRunner().invoke(app, ["launchservices", "regeneration", "--trace", str(trace), "--audit-log", str(audit), "--json"])
    second = CliRunner().invoke(app, ["launchservices", "regeneration", "--trace", str(trace), "--audit-log", str(audit), "--json"])

    assert human.exit_code == 0
    assert "LaunchServices regeneration analysis" in human.stdout
    assert "Regenerator: GoogleUpdater LaunchAgent" in human.stdout
    assert "Observed" in human.stdout
    assert "Correlated" in human.stdout
    assert "Unknown" in human.stdout
    assert json.loads(first.stdout) == json.loads(second.stdout)


def test_regeneration_without_trace_keeps_unknown_explicit_and_low_confidence(monkeypatch):
    snap = snapshot()
    monkeypatch.setattr("macos_state_explorer.cli.create_snapshot", lambda fast=False: snap)

    result = CliRunner().invoke(app, ["launchservices", "regeneration", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    target = next(item for item in payload["generations"] if item["product_family"] == "Google Chrome" and item["classification"] == "STALE")
    assert target["regenerator"] == "Unknown"
    assert target["confidence"] <= 0.35
    assert target["unknown_evidence"]
    assert all(item["category"] in {"Observed", "Correlated", "Inferred", "Unknown"} for group in [target["observed_evidence"], target["correlated_evidence"], target["inferred_evidence"], target["unknown_evidence"]] for item in group)


def test_local_network_report_and_support_bundle_include_regeneration(monkeypatch, tmp_path):
    snap = snapshot()
    trace_dir = write_trace(tmp_path / "trace")
    trace = trace_analysis()
    report = build_local_network_report(snap, trace_analysis=trace)

    payload = report.to_json_dict()
    bundle = write_local_network_support_bundle(report, tmp_path / "bundle", branch_id="trace-local-network", trace_path=trace_dir)

    assert "launchservices_regeneration_summary" in payload
    assert payload["launchservices_regeneration_summary"]["top_regenerator"] == "GoogleUpdater LaunchAgent"
    assert "LaunchServices regeneration" in report.render_text()
    assert (bundle / "regeneration.json").exists()
    assert (bundle / "regeneration.txt").exists()
    assert json.loads((bundle / "regeneration.json").read_text())["command"] == "launchservices regeneration"
    assert "LaunchServices regeneration analysis" in (bundle / "regeneration.txt").read_text()


def test_bundle_diff_includes_regeneration_diff(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "launchservices_regeneration_summary": {"top_regenerator": "Unknown", "high_confidence_generation_count": 0, "unknown_generation_count": 1}}))
    (after / "report.json").write_text(json.dumps({"command": "report local-network", "evidence": [], "launchservices_regeneration_summary": {"top_regenerator": "GoogleUpdater LaunchAgent", "high_confidence_generation_count": 1, "unknown_generation_count": 0}}))

    result = CliRunner().invoke(app, ["diff", "bundles", str(before), str(after), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["regeneration_diff"] == {
        "regenerator_before": "Unknown",
        "regenerator_after": "GoogleUpdater LaunchAgent",
        "high_confidence_delta": 1,
        "unknown_delta": -1,
    }
    assert "launchservices_regeneration_summary" in payload["changed_fields"]


def test_regeneration_documentation_and_version_updated():
    docs = "\n".join(Path(path).read_text() for path in ["README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "docs/LAUNCHSERVICES_OUTCOME_ENGINE.md"])
    pyproject = Path("pyproject.toml").read_text()

    assert "Regeneration Analysis Engine" in docs
    assert "Observed" in docs and "Correlated" in docs and "Inferred" in docs and "Unknown" in docs
    assert "WASP Prism" in docs
    assert "WASP Lens" not in docs
    assert 'version = "1.1.0"' in pyproject
