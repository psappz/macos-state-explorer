from __future__ import annotations
from pathlib import Path
from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import sqlite_overview, run_shell

TERMS = ["LocalNetwork", "kTCCServiceLocalNetwork", "Local Network", "Chrome", "Google", "Bonjour", "NWBrowser"]


class TCCCollector(Collector):
    name = "tcc"

    def collect_payload(self):
        user = str(Path.home() / "Library/Application Support/com.apple.TCC/TCC.db")
        system = "/Library/Application Support/com.apple.TCC/TCC.db"
        reg = "/Library/Application Support/com.apple.TCC/REG.db"
        return {
            "user_tcc": sqlite_overview(user, TERMS),
            "system_tcc": sqlite_overview(system, TERMS),
            "regdb": sqlite_overview(reg, TERMS),
            "direct_localnetwork_query": run_shell(
                f"sqlite3 {user!r} \"SELECT service,client,auth_value,last_modified FROM access WHERE service='kTCCServiceLocalNetwork';\""
            ),
            "direct_chrome_query": run_shell(
                f"sqlite3 {user!r} \"SELECT service,client,auth_value,last_modified FROM access WHERE client LIKE '%Chrome%' OR client LIKE '%google%';\""
            ),
        }
