from __future__ import annotations

import json

from typer.testing import CliRunner

from macos_state_explorer.cli import app
from macos_state_explorer.tracers.local_network import analyze_trace, build_trace_timeline

CSSTORE = "/private/var/folders/zz/com.apple.LaunchServices/com.apple.LaunchServices-3027.csstore"
CSSTORE_WITH_SPACE = "/private/var/folders/zz/LaunchServices Cache/com.apple.LaunchServices-3027.csstore"
CSSTORE_WITH_PARENS = "/private/var/folders/zz/(A)/com.apple.LaunchServices-3027.csstore"


def write_fs_usage_trace(tmp_path, rows: list[str]):
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "fs_usage.txt").write_text("\n".join(rows) + "\n")
    return trace


def fs_usage_events(trace):
    return [event for event in analyze_trace(trace)["normalized_events"] if event["source"] == "fs_usage"]


def test_fs_usage_normalizes_common_process_pid_row_forms(tmp_path):
    trace = write_fs_usage_trace(
        tmp_path,
        [
            f"10:15:01.100000 SecurityPrivacyExtension read {CSSTORE}",
            f"10:15:01.200000 SecurityPrivacyExtension.4815 stat64 {CSSTORE}",
            f"10:15:01.300000 SecurityPrivacyExtension[4816] access {CSSTORE}",
            f"10:15:01.400000 123 tccd mmap {CSSTORE}",
        ],
    )

    events = fs_usage_events(trace)

    assert [(event["process"], event["pid"], event["operation"], event["file_path"]) for event in events] == [
        ("SecurityPrivacyExtension", None, "read", CSSTORE),
        ("SecurityPrivacyExtension", 4815, "stat", CSSTORE),
        ("SecurityPrivacyExtension", 4816, "access", CSSTORE),
        ("tccd", 123, "mmap", CSSTORE),
    ]
    assert all(event["signal"] == "launchservices_csstore" for event in events)
    assert all(event["process"] for event in events)


def test_fs_usage_preserves_paths_with_spaces_parentheses_and_trailing_fields(tmp_path):
    trace = write_fs_usage_trace(
        tmp_path,
        [
            f"10:15:02.100000 SecurityPrivacyExtension.4815 open {CSSTORE_WITH_SPACE} 0.000123 W",
            f"10:15:02.200000 tccd[123] close {CSSTORE_WITH_PARENS} 0.000012 EACCES",
        ],
    )

    events = fs_usage_events(trace)

    assert events[0]["file_path"] == CSSTORE_WITH_SPACE
    assert events[0]["process"] == "SecurityPrivacyExtension"
    assert events[0]["pid"] == 4815
    assert events[0]["operation"] == "open"
    assert events[1]["file_path"] == CSSTORE_WITH_PARENS
    assert events[1]["process"] == "tccd"
    assert events[1]["pid"] == 123
    assert events[1]["operation"] == "close"
    assert events[1]["raw_reference"].endswith("EACCES")


def test_fs_usage_unknown_attribution_is_explicit_and_low_confidence(tmp_path):
    row = f"10:15:03.100000 ??? ??? {CSSTORE}"
    trace = write_fs_usage_trace(tmp_path, [row])

    event = fs_usage_events(trace)[0]

    assert event["process"] == "unknown"
    assert event["pid"] is None
    assert event["operation"] == "cache access"
    assert event["file_path"] == CSSTORE
    assert event["raw_reference"] == row
    assert event["confidence"] < 0.8


def test_trace_timeline_renders_explicit_unknown_for_unattributed_csstore_rows(tmp_path):
    trace = write_fs_usage_trace(
        tmp_path,
        [
            f"10:15:04.100000 SecurityPrivacyExtension.4815 read {CSSTORE}",
            f"10:15:04.200000 malformed {CSSTORE}",
        ],
    )
    analysis = analyze_trace(trace)
    (trace / "analysis.json").write_text(json.dumps(analysis))

    result = CliRunner().invoke(app, ["trace", "timeline", str(trace)])

    assert result.exit_code == 0
    assert f"SecurityPrivacyExtension pid=4815 — read {CSSTORE}" in result.stdout
    assert f"unknown — cache access {CSSTORE}" in result.stdout
    assert "  — cache access" not in result.stdout


def test_fs_usage_normalization_preserves_stable_additive_json_contract(tmp_path):
    trace = write_fs_usage_trace(tmp_path, [f"10:15:05.100000 123 tccd read {CSSTORE} 0.000001"])

    event = fs_usage_events(trace)[0]
    timeline = build_trace_timeline(analyze_trace(trace)).to_json_dict()

    assert list(event)[:15] == [
        "timestamp",
        "timestamp_sort",
        "process",
        "pid",
        "parent_pid",
        "thread_id",
        "executable_path",
        "subsystem",
        "source",
        "source_file",
        "file_path",
        "operation",
        "signal",
        "confidence",
        "raw_reference",
    ]
    assert timeline["events"][0]["process"] == "tccd"
    assert timeline["events"][0]["pid"] == 123
    assert json.dumps(timeline, sort_keys=True) == json.dumps(build_trace_timeline(analyze_trace(trace)).to_json_dict(), sort_keys=True)
