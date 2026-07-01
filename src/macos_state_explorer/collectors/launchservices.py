from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import run_shell

LSREGISTER = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

KEYS = {
    "bundle id": "bundle_id",
    "path": "path",
    "identifier": "identifier",
    "name": "name",
    "displayName": "display_name",
    "teamID": "team_id",
    "versionString": "version",
    "displayVersion": "display_version",
    "reg date": "reg_date",
    "rec mod date": "rec_mod_date",
    "mod date": "mod_date",
    "mount state": "mount_state",
    "directory": "directory",
    "executable": "executable",
    "bundle flags": "bundle_flags",
    "item flags": "item_flags",
    "activityTypes": "activity_types",
    "trustedCodeSignatures": "trusted_code_signatures",
}


def clean_path(value: str) -> str:
    path = value.split(" (0x")[0].strip()
    if path.startswith("~"):
        path = path.replace("~", str(Path.home()), 1)
    return path


def classify(entry: dict[str, Any]) -> str:
    if entry.get("node_not_found") and entry.get("path_exists") is False:
        return "ORPHANED"
    if entry.get("volume_exists") is False:
        return "MISSING_VOLUME"
    if entry.get("path_exists") is False:
        return "STALE"
    if entry.get("path_exists") is True:
        return "ACTIVE"
    return "UNKNOWN"


def parse_lsdump(dump: str, terms: list[str] | None = None) -> list[dict[str, Any]]:
    terms = terms or ["chrome", "google", "localnetwork", "bonjour", "edge", "safari", "firefox"]
    blocks = re.split(r"\n-{20,}\n", dump)
    entries = []
    for block in blocks:
        low = block.lower()
        if not any(t.lower() in low for t in terms):
            continue
        entry: dict[str, Any] = {
            "node_not_found": "Bundle node not found on disk" in block,
            "raw_preview": block[:8000],
        }
        for line in block.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            if k.strip() in KEYS:
                entry[KEYS[k.strip()]] = v.strip()
        if "path" in entry:
            p = clean_path(entry["path"])
            entry["path_clean"] = p
            entry["path_exists"] = Path(p).exists()
            if p.startswith("/Volumes/"):
                parts = Path(p).parts
                vol = "/" + "/".join(parts[1:3]) if len(parts) >= 3 else "/Volumes"
                entry["volume"] = vol
                entry["volume_exists"] = Path(vol).exists()
            else:
                entry["volume"] = "/"
                entry["volume_exists"] = True
        entry["classification"] = classify(entry)
        entries.append(entry)
    return entries


class LaunchServicesCollector(Collector):
    name = "launchservices"

    def collect_payload(self):
        dump = run_shell(f"'{LSREGISTER}' -dump 2>/dev/null", timeout=300)
        entries = parse_lsdump(dump.get("stdout", ""))
        counts: dict[str, int] = {}
        for e in entries:
            counts[e["classification"]] = counts.get(e["classification"], 0) + 1
        return {
            "entry_count": len(entries),
            "classification_counts": counts,
            "entries": entries,
            "stale_entries": [e for e in entries if e["classification"] in {"ORPHANED", "STALE", "MISSING_VOLUME"}],
            "candidate_files": run_shell(
                "find \"$HOME/Library\" /Library /private/var/db "
                "\\( -iname '*LaunchServices*' -o -iname '*lsregister*' -o -iname '*sharedfilelist*' \\) "
                "2>/dev/null | head -n 2000",
                timeout=180,
            ),
        }
