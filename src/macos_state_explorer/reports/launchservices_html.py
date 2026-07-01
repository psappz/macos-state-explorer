from __future__ import annotations

import html
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from macos_state_explorer.launchservices.grouping import BundleGroup, bundle_statistics, group_records
from macos_state_explorer.launchservices.models import LaunchServicesRecord, LaunchServicesStatus


def write_launchservices_html(out: Path, payload: Mapping[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "launchservices.html").write_text(render_launchservices_html(payload))


def render_launchservices_html(payload: Mapping[str, Any]) -> str:
    records = _records_from_payload(payload)
    groups = group_records(records)
    stats = bundle_statistics(records)
    duplicate_bundle_ids = set(stats["duplicate_bundle_ids"])
    bundle_sections = "\n".join(
        _render_bundle_section(group, key in duplicate_bundle_ids)
        for key, group in sorted(groups.items(), key=lambda item: item[0].lower())
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LaunchServices Explorer</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #f6f7f8;
  --panel: #ffffff;
  --text: #17191c;
  --muted: #5f6670;
  --line: #d9dee5;
  --accent: #0f6bff;
  --warn: #a14c00;
  --danger: #b42318;
  --ok: #087443;
  --unknown: #5f6670;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #101214;
    --panel: #181b1f;
    --text: #eef1f4;
    --muted: #a3abb5;
    --line: #30363d;
    --accent: #6ca6ff;
    --warn: #f5a524;
    --danger: #ff8a80;
    --ok: #52d273;
    --unknown: #a3abb5;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
header {{
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 1rem clamp(1rem, 4vw, 2rem);
  background: color-mix(in srgb, var(--bg) 90%, transparent);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}}
main {{ padding: 1rem clamp(1rem, 4vw, 2rem) 2rem; }}
h1 {{ margin: 0 0 .75rem; font-size: 1.6rem; }}
.toolbar {{ display: grid; gap: .75rem; grid-template-columns: minmax(16rem, 1fr) auto; align-items: center; }}
input[type="search"] {{
  width: 100%;
  min-height: 2.5rem;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: .55rem .75rem;
  color: var(--text);
  background: var(--panel);
}}
.stats {{ display: flex; flex-wrap: wrap; gap: .5rem; }}
.stat, .badge, .warning {{
  display: inline-flex;
  align-items: center;
  min-height: 1.6rem;
  border-radius: 999px;
  padding: .2rem .55rem;
  border: 1px solid var(--line);
  white-space: nowrap;
}}
.stat {{ background: var(--panel); color: var(--muted); }}
.bundle {{
  margin: .85rem 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  overflow: clip;
}}
.bundle[hidden] {{ display: none; }}
summary {{
  cursor: pointer;
  display: grid;
  gap: .5rem;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  padding: .85rem 1rem;
}}
summary:hover {{ background: color-mix(in srgb, var(--accent) 8%, transparent); }}
.title {{ min-width: 0; }}
.name {{ font-weight: 700; overflow-wrap: anywhere; }}
.bundle-id {{ color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }}
.badges {{ display: flex; flex-wrap: wrap; gap: .35rem; justify-content: flex-end; }}
.badge {{ font-size: .76rem; font-weight: 650; }}
.status-active {{ color: var(--ok); }}
.status-stale, .status-orphaned, .status-missing-volume, .status-broken {{ color: var(--danger); }}
.status-duplicate, .status-shadowed, .status-superseded {{ color: var(--warn); }}
.status-unknown {{ color: var(--unknown); }}
.warnings {{ display: flex; flex-wrap: wrap; gap: .4rem; padding: 0 1rem .8rem; }}
.warning {{ color: var(--warn); background: color-mix(in srgb, var(--warn) 10%, transparent); }}
.warning.danger {{ color: var(--danger); background: color-mix(in srgb, var(--danger) 10%, transparent); }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
th, td {{ padding: .6rem .75rem; border-top: 1px solid var(--line); text-align: left; vertical-align: top; }}
th {{ color: var(--muted); font-size: .78rem; font-weight: 650; }}
td {{ overflow-wrap: anywhere; }}
.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.empty {{ padding: 2rem; color: var(--muted); text-align: center; }}
@media (max-width: 780px) {{
  .toolbar, summary {{ grid-template-columns: 1fr; }}
  .badges {{ justify-content: flex-start; }}
  table, thead, tbody, tr, th, td {{ display: block; }}
  thead {{ display: none; }}
  td {{ border-top: 0; padding: .35rem 1rem; }}
  td::before {{ content: attr(data-label); display: block; color: var(--muted); font-size: .72rem; }}
  tr {{ border-top: 1px solid var(--line); padding: .45rem 0; }}
}}
</style>
</head>
<body>
<header>
  <h1>LaunchServices Explorer</h1>
  <div class="toolbar">
    <input id="search" type="search" placeholder="Search bundles, versions, paths, statuses" aria-label="Search LaunchServices bundles">
    {_render_stats(stats)}
  </div>
</header>
<main id="bundles">
  {bundle_sections or '<p class="empty">No LaunchServices records found.</p>'}
</main>
<script>
const search = document.querySelector("#search");
const bundles = Array.from(document.querySelectorAll(".bundle"));
search?.addEventListener("input", () => {{
  const query = search.value.trim().toLowerCase();
  for (const bundle of bundles) {{
    bundle.hidden = query.length > 0 && !bundle.dataset.search.includes(query);
  }}
}});
</script>
</body>
</html>
"""


def _records_from_payload(payload: Mapping[str, Any]) -> list[LaunchServicesRecord]:
    return [
        record if isinstance(record, LaunchServicesRecord) else LaunchServicesRecord.model_validate(record)
        for record in payload.get("entries", [])
    ]


def _render_stats(stats: Mapping[str, Any]) -> str:
    status_counts = stats.get("status_counts", {})
    status_summary = ", ".join(
        f"{_escape(_status_value(status))}: {count}" for status, count in sorted(status_counts.items())
    )
    items = [
        f"Bundles: {stats.get('total_bundles', 0)}",
        f"Duplicate IDs: {len(stats.get('duplicate_bundle_ids', []))}",
        f"Duplicate paths: {len(stats.get('duplicate_paths', {}))}",
    ]
    if status_summary:
        items.append(f"Statuses: {status_summary}")
    return '<div class="stats">' + "".join(f'<span class="stat">{_escape(item)}</span>' for item in items) + "</div>"


def _render_bundle_section(group: BundleGroup, duplicate_bundle_id: bool) -> str:
    bundle_id = group.bundle_id or "Missing bundle ID"
    display_name = group.display_name or bundle_id
    search_text = _search_text(
        [display_name, bundle_id, *group.versions, *group.paths, *(_status_value(status) for status in group.statuses)]
    )
    warnings = _warnings_for_group(group, duplicate_bundle_id)
    badge_html = "".join(_status_badge(status) for status in group.statuses)
    table_rows = "".join(_render_record_row(record) for record in group.records)
    warning_html = (
        '<div class="warnings">' + "".join(_render_warning(label, danger) for label, danger in warnings) + "</div>"
        if warnings
        else ""
    )
    return f"""
<details class="bundle" data-search="{_escape(search_text)}" open>
  <summary>
    <div class="title">
      <div class="name">{_escape(display_name)}</div>
      <div class="bundle-id">{_escape(bundle_id)}</div>
    </div>
    <div class="badges">{badge_html}<span class="stat">{len(group.records)} records</span></div>
  </summary>
  {warning_html}
  <table>
    <thead>
      <tr>
        <th>Version</th>
        <th>Registration</th>
        <th>Status</th>
        <th>Path</th>
        <th>Volume</th>
        <th>Sequence</th>
      </tr>
    </thead>
    <tbody>{table_rows}</tbody>
  </table>
</details>
"""


def _render_record_row(record: LaunchServicesRecord) -> str:
    path = record.path_clean or record.path or ""
    exists = "exists" if record.path_exists is True else "missing" if record.path_exists is False else "unknown"
    volume = record.volume or ""
    volume_exists = "exists" if record.volume_exists is True else "missing" if record.volume_exists is False else ""
    return f"""
<tr>
  <td data-label="Version">{_escape(record.version or record.display_version or "")}</td>
  <td data-label="Registration">{_escape(record.registration_date or "")}</td>
  <td data-label="Status">{_status_badge(record.classification)}</td>
  <td data-label="Path"><span class="mono">{_escape(path)}</span><br><small>{_escape(exists)}</small></td>
  <td data-label="Volume"><span class="mono">{_escape(volume)}</span><br><small>{_escape(volume_exists)}</small></td>
  <td data-label="Sequence">{_escape(str(record.sequence_number) if record.sequence_number is not None else "")}</td>
</tr>
"""


def _warnings_for_group(group: BundleGroup, duplicate_bundle_id: bool) -> list[tuple[str, bool]]:
    warnings: list[tuple[str, bool]] = []
    if duplicate_bundle_id:
        warnings.append(("Duplicate bundle identifier", False))
    if len(group.paths) > 1:
        warnings.append(("Multiple registered paths", False))
    if any(record.classification == LaunchServicesStatus.ORPHANED for record in group.records):
        warnings.append(("Orphaned registration", True))
    if any(
        record.classification == LaunchServicesStatus.MISSING_VOLUME or record.volume_exists is False
        for record in group.records
    ):
        warnings.append(("Missing volume", True))
    return warnings


def _render_warning(label: str, danger: bool) -> str:
    class_name = "warning danger" if danger else "warning"
    return f'<span class="{class_name}">{_escape(label)}</span>'


def _status_badge(status: LaunchServicesStatus) -> str:
    status_value = _status_value(status)
    class_name = f"badge status-{status_value.lower().replace('_', '-')}"
    return f'<span class="{class_name}">{_escape(status_value)}</span>'


def _status_value(status: LaunchServicesStatus | str) -> str:
    return status.value if isinstance(status, LaunchServicesStatus) else str(status)


def _search_text(values: Iterable[str]) -> str:
    return " ".join(value for value in values if value).lower()


def _escape(value: str) -> str:
    return html.escape(value, quote=True)
