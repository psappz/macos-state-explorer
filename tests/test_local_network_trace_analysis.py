from __future__ import annotations

from macos_state_explorer.tracers.local_network import analyze_trace, render_trace_html


def test_trace_analysis_builds_correlated_timeline(tmp_path):
    (tmp_path / "log_stream.txt").write_text(
        "\n".join(
            [
                "2026-07-01 12:00:01.100000+0200 System Settings SecurityPrivacyExtension.appex opened Local Network",
                "2026-07-01 12:00:03.100000+0200 tccd TCC.framework checked kTCCServiceLocalNetwork for Chrome",
                "2026-07-01 12:00:04.100000+0200 lsd com.google.Chrome.code_sign_clone registered",
            ]
        )
    )
    (tmp_path / "fs_usage.txt").write_text(
        "12:00:02.200 lsd open /private/var/folders/zz/com.apple.LaunchServices-123.csstore\n"
    )
    (tmp_path / "process_loop.txt").write_text(
        "Wed Jul  1 12:00:05 CEST 2026\nrunningboardd evaluating Google Chrome\n"
    )

    analysis = analyze_trace(tmp_path)

    events = analysis["timeline_events"]
    assert [event["signal"] for event in events[:4]] == [
        "securityprivacyextension",
        "launchservices_csstore",
        "tcc_localnetwork",
        "chrome_code_sign_clone",
    ]
    assert analysis["signal_counts"]["securityprivacyextension"] == 1
    assert analysis["signal_counts"]["launchservices_csstore"] == 1
    assert analysis["signal_counts"]["chrome_code_sign_clone"] == 1
    assert analysis["correlation_summary"][0]["signal"] == "securityprivacyextension"
    assert analysis["correlation_summary"][0]["sources"] == ["log_stream.txt"]


def test_trace_html_renders_timeline_and_signal_summary(tmp_path):
    (tmp_path / "log_stream.txt").write_text(
        "2026-07-01 12:00:01.100000+0200 System Settings SecurityPrivacyExtension.appex opened Local Network\n"
    )
    analysis = analyze_trace(tmp_path)

    html = render_trace_html(analysis)

    assert "Root-cause Signals" in html
    assert "Correlated Timeline" in html
    assert "securityprivacyextension" in html
    assert "SecurityPrivacyExtension.appex" in html
