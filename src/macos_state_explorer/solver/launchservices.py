from __future__ import annotations

from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.diagnostics.framework import DiagnosticSolution, FrameworkDiagnosticEngine
from macos_state_explorer.diagnostics.launchservices.module import LAUNCHSERVICES_MODULE

LaunchServicesSolution = DiagnosticSolution


def build_launchservices_solution(snapshot: Snapshot) -> LaunchServicesSolution:
    return FrameworkDiagnosticEngine(LAUNCHSERVICES_MODULE).solve(snapshot)
