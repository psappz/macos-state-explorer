from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticSolution, build_support_bundle
from macos_state_explorer.solver.launchservices import build_launchservices_solution


@dataclass(frozen=True)
class LaunchServicesReport:
    solution: DiagnosticSolution

    def render_text(self) -> str:
        return "\n".join(
            [
                "LaunchServices diagnostic report",
                "================================",
                "",
                self.solution.render_text(),
            ]
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": "report launchservices",
            "solution": self.solution.to_json_dict(),
            "supporting_commands": list(self.solution.supporting_commands),
            "bundle_schema_version": 1,
        }


def build_launchservices_report(snapshot: Snapshot) -> LaunchServicesReport:
    return LaunchServicesReport(solution=build_launchservices_solution(snapshot))


def write_launchservices_support_bundle(report: LaunchServicesReport, bundle_path: Path) -> Path:
    return build_support_bundle(
        bundle_path,
        report_json=report.to_json_dict(),
        report_text=report.render_text(),
        command_metadata={
            "command": "mse report launchservices --bundle",
            "bundle_schema_version": 1,
        },
        environment=_environment_summary(),
    )


def _environment_summary() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
    }
