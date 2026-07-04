from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.exports.framework import (
    EvidenceBundleExport,
    EvidenceBundleExportRequest,
    EvidenceBundleRegistry,
    export_evidence_bundle,
)


def _snapshot() -> Snapshot:
    return Snapshot(
        host="export-host",
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
                payload={
                    "stale_entries": [
                        {"bundle_id": "com.google.Chrome", "path": "/Applications/Google Chrome.app"},
                    ],
                    "entries": [
                        {
                            "bundle_id": "com.google.Chrome",
                            "path": "/Applications/Google Chrome.app",
                            "classification": "STALE",
                        }
                    ],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices.csstore\n"},
                },
            ),
        ],
    )


@dataclass(frozen=True)
class DummyCrossVendorProvider:
    def export(self, request: EvidenceBundleExportRequest) -> EvidenceBundleExport:
        request.output.mkdir(parents=True, exist_ok=True)
        (request.output / "cdn-dns-evidence.json").write_text(
            json.dumps({"target": request.target, "issue": request.issue}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return EvidenceBundleExport(
            manifest={
                "export_schema_version": 1,
                "audience": request.audience,
                "target": request.target,
                "issue": request.issue,
                "provider_id": "dummy-cdn-dns",
                "artifacts": ["cdn-dns-evidence.json"],
            },
            output=request.output,
        )


def test_export_core_is_provider_registry_driven_and_not_apple_specific(tmp_path: Path):
    registry = EvidenceBundleRegistry()
    registry.register(
        audience="customer-report",
        target="akamai",
        issue="cdn-dns",
        provider=DummyCrossVendorProvider(),
    )

    export = export_evidence_bundle(
        EvidenceBundleExportRequest(
            audience="customer-report",
            target="akamai",
            issue="cdn-dns",
            output=tmp_path / "export",
        ),
        registry=registry,
    )

    manifest = json.loads((export.output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["audience"] == "customer-report"
    assert manifest["target"] == "akamai"
    assert manifest["issue"] == "cdn-dns"
    assert manifest["provider_id"] == "dummy-cdn-dns"
    assert (export.output / "cdn-dns-evidence.json").exists()


def test_export_evidence_bundle_rejects_unregistered_combination(tmp_path: Path):
    registry = EvidenceBundleRegistry()

    try:
        export_evidence_bundle(
            EvidenceBundleExportRequest(
                audience="vendor-feedback",
                target="cloudflare",
                issue="waap",
                output=tmp_path / "export",
            ),
            registry=registry,
        )
    except ValueError as error:
        assert "No evidence export provider registered" in str(error)
        assert "vendor-feedback/cloudflare/waap" in str(error)
    else:
        raise AssertionError("expected unsupported export combination to fail")


def test_export_evidence_bundle_rejects_existing_non_empty_output(tmp_path: Path):
    output = tmp_path / "export"
    output.mkdir()
    (output / "unrelated-private-file.txt").write_text("do not include", encoding="utf-8")
    registry = EvidenceBundleRegistry()
    registry.register(
        audience="customer-report",
        target="akamai",
        issue="cdn-dns",
        provider=DummyCrossVendorProvider(),
    )

    try:
        export_evidence_bundle(
            EvidenceBundleExportRequest(
                audience="customer-report",
                target="akamai",
                issue="cdn-dns",
                output=output,
            ),
            registry=registry,
        )
    except ValueError as error:
        assert "Export output directory already exists and is not empty" in str(error)
    else:
        raise AssertionError("expected non-empty export directory to fail closed")


def test_export_evidence_bundle_rejects_symlink_output(tmp_path: Path):
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    symlink_output = tmp_path / "linked-output"
    symlink_output.symlink_to(real_output, target_is_directory=True)
    registry = EvidenceBundleRegistry()
    registry.register(
        audience="customer-report",
        target="akamai",
        issue="cdn-dns",
        provider=DummyCrossVendorProvider(),
    )

    try:
        export_evidence_bundle(
            EvidenceBundleExportRequest(
                audience="customer-report",
                target="akamai",
                issue="cdn-dns",
                output=symlink_output,
            ),
            registry=registry,
        )
    except ValueError as error:
        assert "Export output path must not be a symlink" in str(error)
    else:
        raise AssertionError("expected symlink export path to fail closed")


def test_initial_local_network_apple_vendor_feedback_export_writes_manifest_and_support_artifacts(tmp_path: Path, monkeypatch):
    from macos_state_explorer.exports import local_network as local_network_export

    def fake_bundle_writer(report: Any, bundle_path: Path, *, branch_id: str, trace_path: Path | None = None, launchservices_audit_log=None) -> Path:
        bundle_path.mkdir(parents=True, exist_ok=True)
        (bundle_path / "report.json").write_text(json.dumps(report.to_json_dict(), sort_keys=False) + "\n", encoding="utf-8")
        (bundle_path / "report.txt").write_text(report.render_text() + "\n", encoding="utf-8")
        return bundle_path

    monkeypatch.setattr(local_network_export, "create_snapshot", lambda fast=True: _snapshot())
    monkeypatch.setattr(local_network_export, "write_local_network_support_bundle", fake_bundle_writer)

    registry = EvidenceBundleRegistry()
    local_network_export.register_local_network_exports(registry)
    export = export_evidence_bundle(
        EvidenceBundleExportRequest(
            audience="vendor-feedback",
            target="apple",
            issue="local-network",
            output=tmp_path / "apple-feedback",
        ),
        registry=registry,
    )

    manifest = json.loads((export.output / "manifest.json").read_text(encoding="utf-8"))
    assert list(manifest)[:7] == [
        "export_schema_version",
        "audience",
        "target",
        "issue",
        "provider_id",
        "generated_by",
        "artifacts",
    ]
    assert manifest["audience"] == "vendor-feedback"
    assert manifest["target"] == "apple"
    assert manifest["issue"] == "local-network"
    assert manifest["provider_id"] == "local-network.apple.vendor-feedback"
    assert {artifact["path"] for artifact in manifest["artifacts"]} >= {
        "vendor-feedback.md",
        "support-bundle/report.json",
        "support-bundle/report.txt",
    }
    brief = (export.output / "vendor-feedback.md").read_text(encoding="utf-8")
    assert "Audience: vendor-feedback" in brief
    assert "Target: apple" in brief
    assert "Issue: local-network" in brief
    assert "This export is generated by the generic evidence export framework." in brief


def test_export_evidence_bundle_cli_initial_contract(tmp_path: Path, monkeypatch):
    from macos_state_explorer.exports import local_network as local_network_export

    def fake_bundle_writer(report: Any, bundle_path: Path, *, branch_id: str, trace_path: Path | None = None, launchservices_audit_log=None) -> Path:
        bundle_path.mkdir(parents=True, exist_ok=True)
        (bundle_path / "report.json").write_text(json.dumps(report.to_json_dict(), sort_keys=False) + "\n", encoding="utf-8")
        (bundle_path / "report.txt").write_text(report.render_text() + "\n", encoding="utf-8")
        return bundle_path

    monkeypatch.setattr(local_network_export, "create_snapshot", lambda fast=True: _snapshot())
    monkeypatch.setattr(local_network_export, "write_local_network_support_bundle", fake_bundle_writer)

    result = CliRunner().invoke(
        app,
        [
            "export",
            "evidence-bundle",
            "--audience",
            "vendor-feedback",
            "--target",
            "apple",
            "--issue",
            "local-network",
            "--output",
            str(tmp_path / "cli-export"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Evidence bundle export:" in result.output
    manifest = json.loads((tmp_path / "cli-export" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["audience"] == "vendor-feedback"
    assert manifest["target"] == "apple"
    assert manifest["issue"] == "local-network"


def test_export_evidence_bundle_cli_reports_unsupported_combination(tmp_path: Path):
    result = CliRunner().invoke(
        app,
        [
            "export",
            "evidence-bundle",
            "--audience",
            "vendor-feedback",
            "--target",
            "cloudflare",
            "--issue",
            "local-network",
            "--output",
            str(tmp_path / "unsupported"),
        ],
    )

    assert result.exit_code == 1
    assert "No evidence export provider registered" in result.output
