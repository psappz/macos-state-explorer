from __future__ import annotations
from pathlib import Path
from macos_state_explorer.core.snapshot import create_snapshot
from macos_state_explorer.core.util import write_json
from macos_state_explorer.tracers.local_network import trace_local_network


def experiment_local_network(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    before = create_snapshot(fast=True)
    write_json(out / "before.json", before)
    trace_local_network(out / "trace")
    after = create_snapshot(fast=True)
    write_json(out / "after.json", after)
    print(f"Experiment: {out}")
