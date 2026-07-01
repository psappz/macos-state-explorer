from __future__ import annotations

from typing import Any

from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import run_shell
from macos_state_explorer.launchservices.grouping import classification_counts, stale_records
from macos_state_explorer.launchservices.parser import DEFAULT_TERMS, parse_lsdump

LSREGISTER = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"


class LaunchServicesCollector(Collector):
    name = "launchservices"

    def collect_payload(self):
        dump = run_shell(f"'{LSREGISTER}' -dump 2>/dev/null", timeout=300)
        records = parse_lsdump(dump.get("stdout", ""), terms=DEFAULT_TERMS)
        entries: list[dict[str, Any]] = [record.model_dump(mode="python") for record in records]
        stale_entries = [record.model_dump(mode="python") for record in stale_records(records)]
        return {
            "entry_count": len(entries),
            "classification_counts": classification_counts(records),
            "entries": entries,
            "stale_entries": stale_entries,
            "candidate_files": run_shell(
                "find \"$HOME/Library\" /Library /private/var/db "
                "\\( -iname '*LaunchServices*' -o -iname '*lsregister*' -o -iname '*sharedfilelist*' \\) "
                "2>/dev/null | head -n 2000",
                timeout=180,
            ),
        }
