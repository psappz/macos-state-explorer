from __future__ import annotations
from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import run_shell

FRAMEWORKS = [
    "/System/Library/PrivateFrameworks/TCC.framework/TCC",
    "/System/Library/PrivateFrameworks/AppPrivacy.framework/AppPrivacy",
    "/System/Library/Frameworks/Network.framework/Network",
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/LaunchServices",
    "/System/Library/PrivateFrameworks/Settings.framework/Settings",
    "/System/Library/PrivateFrameworks/SettingsFoundation.framework/SettingsFoundation",
]


class FrameworksCollector(Collector):
    name = "frameworks"

    def collect_payload(self):
        out = {}
        for f in FRAMEWORKS:
            out[f] = run_shell(
                f"if [ -f '{f}' ]; then strings '{f}' 2>/dev/null | "
                "grep -Ei 'LocalNetwork|Local Network|kTCCServiceLocalNetwork|Bonjour|NWBrowser|Privacy|TCC|LaunchServices|NetworkPrivacy' | head -n 1000; "
                "else echo MISSING; fi",
                timeout=120,
            )
        return out
