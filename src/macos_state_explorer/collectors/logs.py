from __future__ import annotations
from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import run_shell


class LogsCollector(Collector):
    name = "logs"

    def collect_payload(self):
        return {
            "privacy_recent": run_shell(
                "log show --last 6h --style compact "
                "--predicate 'process == \"tccd\" OR process == \"dprivacyd\" OR process == \"webprivacyd\" "
                "OR process == \"transparencyd\" OR process == \"lsd\" "
                "OR eventMessage CONTAINS[c] \"LocalNetwork\" "
                "OR eventMessage CONTAINS[c] \"Local Network\" "
                "OR eventMessage CONTAINS[c] \"Chrome\" "
                "OR eventMessage CONTAINS[c] \"Google\"' | tail -n 3000",
                timeout=240,
            )
        }
