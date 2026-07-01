from __future__ import annotations
from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import run_cmd, run_shell


class SystemCollector(Collector):
    name = "system"

    def collect_payload(self):
        return {
            "sw_vers": run_cmd(["sw_vers"]),
            "uname": run_cmd(["uname", "-a"]),
            "csrutil": run_shell("csrutil status"),
            "spctl": run_shell("spctl --status"),
            "id": run_shell("id"),
            "python": run_shell("python3 --version; which python3"),
        }
