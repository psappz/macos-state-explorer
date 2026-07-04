from __future__ import annotations

from pathlib import Path
from typing import Any

from macos_state_explorer.collectors.base import Collector
from macos_state_explorer.core.util import run_shell
from macos_state_explorer.launchservices.grouping import classification_counts, stale_records
from macos_state_explorer.launchservices.parser import DEFAULT_TERMS, parse_lsdump

LSREGISTER = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"


def candidate_launchservices_files(
    home: Path | None = None,
    roots: list[Path] | None = None,
    limit: int = 2000,
) -> list[str]:
    """Return a bounded, focused list of LaunchServices-related files.

    This intentionally avoids an unbounded `find $HOME/Library /Library /private/var/db`
    scan. `mse solve local-network` needs prompt diagnostic evidence, not a full
    filesystem crawl that can hang on protected or slow macOS paths.
    """
    home = (home or Path.home()).expanduser()
    roots = roots or [
        home / "Library" / "Preferences",
        home / "Library" / "Application Support" / "com.apple.LaunchServices",
        home / "Library" / "Application Support" / "com.apple.sharedfilelist",
        home / "Library" / "Caches",
        Path("/Library/Preferences"),
        Path("/private/var/db/lsd"),
        Path("/private/var/db/com.apple.xpc.launchd"),
    ]
    patterns = (
        "*LaunchServices*",
        "*lsregister*",
        "*sharedfilelist*",
        "*.csstore",
    )
    found: list[str] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        if len(found) >= limit:
            return
        text = str(path)
        lowered = text.lower()
        if not any(term in lowered for term in ("launchservices", "lsregister", "sharedfilelist", ".csstore")):
            return
        if text not in seen:
            seen.add(text)
            found.append(text)

    for root in roots:
        if len(found) >= limit:
            break
        if not root.exists():
            continue
        for pattern in patterns:
            if len(found) >= limit:
                break
            try:
                for path in root.glob(pattern):
                    add(path)
                    if len(found) >= limit:
                        break
            except (OSError, PermissionError):
                continue

    # Known macOS temp/cache layout for LaunchServices .csstore files, bounded to
    # exactly three wildcard levels instead of a recursive filesystem walk.
    if len(found) < limit:
        for pattern in (
            "/private/var/folders/*/*/*/com.apple.LaunchServices*",
            "/private/var/folders/*/*/*/*.csstore",
        ):
            for path_text in sorted(Path("/").glob(pattern.lstrip("/"))):
                add(path_text)
                if len(found) >= limit:
                    break
            if len(found) >= limit:
                break

    return sorted(found)


class LaunchServicesCollector(Collector):
    name = "launchservices"

    def collect_payload(self):
        dump = run_shell(f"'{LSREGISTER}' -dump 2>/dev/null", timeout=60)
        records = parse_lsdump(dump.get("stdout", ""), terms=DEFAULT_TERMS)
        entries: list[dict[str, Any]] = [record.model_dump(mode="python") for record in records]
        stale_entries = [record.model_dump(mode="python") for record in stale_records(records)]
        candidate_files = candidate_launchservices_files()
        return {
            "entry_count": len(entries),
            "classification_counts": classification_counts(records),
            "entries": entries,
            "stale_entries": stale_entries,
            "candidate_files": {
                "cmd": "bounded Python glob for LaunchServices-related paths",
                "returncode": 0,
                "stdout": "\n".join(candidate_files),
                "stderr": "",
            },
        }
