from __future__ import annotations

from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.diagnostics.local_network.evidence import collect_local_network_evidence
from macos_state_explorer.diagnostics.local_network.verification import verify_local_network
from macos_state_explorer.solver.local_network import build_local_network_solution
from macos_state_explorer.tracers.local_network import analyze_trace


def empty_snapshot() -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={"direct_localnetwork_query": {"stdout": ""}, "user_tcc": {"hits": []}},
            ),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={"stale_entries": [], "candidate_files": {"stdout": ""}},
            ),
        ],
    )


def test_shared_evidence_records_trace_provenance_and_strengthens_confidence(tmp_path):
    (tmp_path / "log_stream.txt").write_text(
        "\n".join(
            [
                "2026-07-01 12:00:01 System Settings SecurityPrivacyExtension.appex opened Local Network",
                "2026-07-01 12:00:02 lsd com.google.Chrome.code_sign_clone registered",
                "2026-07-01 12:00:03 lsd com.google.Chrome.code_sign_clone checked again",
            ]
        )
    )
    analysis = analyze_trace(tmp_path)

    evidence = collect_local_network_evidence(empty_snapshot(), trace_analysis=analysis)
    by_id = {item.id: item for item in evidence}

    assert by_id["LN-E004"].present is True
    assert by_id["LN-E004"].provenance == ["trace"]
    assert by_id["LN-E006"].present is True
    assert by_id["LN-E006"].provenance == ["chrome", "trace"]
    assert by_id["LN-E006"].confidence > 0.9
    assert by_id["LN-E009"].present is False


def test_trace_code_sign_clone_promotes_reinstall_over_more_tracing(tmp_path):
    (tmp_path / "log_stream.txt").write_text(
        "2026-07-01 12:00:02 lsd com.google.Chrome.code_sign_clone registered\n"
    )
    (tmp_path / "fs_usage.txt").write_text(
        "12:00:03 lsd open /private/var/folders/zz/com.apple.LaunchServices-123.csstore\n"
    )
    analysis = analyze_trace(tmp_path)

    solution = build_local_network_solution(empty_snapshot(), trace_analysis=analysis)

    assert solution.repair_plan[0].id == "manual-reinstall-chrome"
    assert {"LN-E005", "LN-E006"}.issubset(set(solution.repair_plan[0].evidence_ids))
    assert "trace" in solution.render_text()


def test_verify_trace_branch_advances_to_reinstall_when_trace_finds_chrome_identity(tmp_path):
    (tmp_path / "log_stream.txt").write_text(
        "2026-07-01 12:00:02 lsd com.google.Chrome.code_sign_clone registered\n"
    )
    analysis = analyze_trace(tmp_path)

    result = verify_local_network(
        empty_snapshot(),
        expected_branch_id="trace-local-network",
        trace_analysis=analysis,
    )

    assert result.status == "FAILED"
    assert result.transition == "advance"
    assert result.next_repair_candidate is not None
    assert result.next_repair_candidate.id == "manual-reinstall-chrome"
    assert "LN-E006" in result.evidence_ids
