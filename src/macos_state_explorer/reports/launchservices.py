from __future__ import annotations

import platform
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticSolution, build_support_bundle
from macos_state_explorer.launchservices.analysis import (
    LaunchServicesAnalysis,
    analysis_from_snapshot_payload,
    render_launchservices_analysis,
)
from macos_state_explorer.solver.launchservices import build_launchservices_solution


@dataclass(frozen=True)
class LaunchServicesReport:
    solution: DiagnosticSolution
    analysis: LaunchServicesAnalysis

    def render_text(self) -> str:
        return "\n".join(
            [
                "LaunchServices diagnostic report",
                "================================",
                "",
                self.solution.render_text(),
                "",
                "Root cause analysis",
                "===================",
                "",
                render_launchservices_analysis(self.analysis),
            ]
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "report launchservices",
            "solution": self.solution.to_json_dict(),
            "analysis": self.analysis.to_json_dict(),
            "supporting_commands": list(self.solution.supporting_commands),
            "bundle_schema_version": 1,
        }

def build_launchservices_report(snapshot: Snapshot) -> LaunchServicesReport:
    payload = next((observation.payload for observation in snapshot.observations if observation.collector == "launchservices"), {})
    return LaunchServicesReport(
        solution=build_launchservices_solution(snapshot),
        analysis=analysis_from_snapshot_payload(payload if isinstance(payload, dict) else {}),
    )



def write_launchservices_support_bundle(report: LaunchServicesReport, bundle_path: Path) -> Path:
    bundle = build_support_bundle(
        bundle_path,
        report_json=report.to_json_dict(),
        report_text=report.render_text(),
        command_metadata={
            "command": "mse report launchservices --bundle",
            "bundle_schema_version": 1,
        },
        environment=_environment_summary(),
    )
    (bundle / "launchservices-analysis.json").write_text(
        json.dumps(report.analysis.to_json_dict(), indent=2, ensure_ascii=False) + "\n"
    )
    return bundle


def _environment_summary() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
    }
