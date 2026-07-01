from __future__ import annotations
from macos_state_explorer.collectors.frameworks import FrameworksCollector
from macos_state_explorer.collectors.launchservices import LaunchServicesCollector
from macos_state_explorer.collectors.logs import LogsCollector
from macos_state_explorer.collectors.processes import ProcessesCollector
from macos_state_explorer.collectors.system import SystemCollector
from macos_state_explorer.collectors.tcc import TCCCollector
from macos_state_explorer.core.model import Snapshot
from macos_state_explorer.core.util import host
from macos_state_explorer.inference.rules import infer

FAST = [SystemCollector, TCCCollector, LaunchServicesCollector, ProcessesCollector]
FULL = [SystemCollector, TCCCollector, LaunchServicesCollector, ProcessesCollector, FrameworksCollector, LogsCollector]


def create_snapshot(fast: bool = False) -> Snapshot:
    snap = Snapshot(host=host())
    for cls in (FAST if fast else FULL):
        snap.observations.append(cls().collect())
    snap.hypotheses = infer(snap)
    return snap
