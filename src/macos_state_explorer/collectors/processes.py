from __future__ import annotations
from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import run_shell


class ProcessesCollector(Collector):
    name = "processes"

    def collect_payload(self):
        pattern = "System Settings|tccd|lsd|runningboardd|dprivacyd|webprivacyd|transparencyd|cfprefsd|networkd|nehelper"
        return {
            "ps": run_shell(f"ps auxww | grep -Ei '{pattern}' | grep -v grep || true"),
            "launchctl_user": run_shell(f"launchctl print gui/$(id -u) 2>/dev/null | grep -Ei -A3 -B3 '{pattern}' || true"),
            "launchctl_system": run_shell(f"launchctl print system 2>/dev/null | grep -Ei -A3 -B3 '{pattern}' || true"),
            "lsof": run_shell(
                f"sudo lsof -nP 2>/dev/null | grep -Ei '{pattern}|TCC|REG|LaunchServices|Privacy|privacy|Chrome|Google|\.db|\.sqlite|\.plist' || true",
                timeout=180,
            ),
        }
