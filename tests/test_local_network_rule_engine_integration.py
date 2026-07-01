from __future__ import annotations

from macos_state_explorer.core.model import Observation, Snapshot
from macos_state_explorer.solver.local_network import build_local_network_solution


def _snapshot_with_complex_evidence() -> Snapshot:
    return Snapshot(
        host="test-host",
        observations=[
            Observation(
                collector="tcc",
                started_at=1,
                ended_at=2,
                payload={
                    "direct_localnetwork_query": {"stdout": ""},
                    "user_tcc": {"hits": []},
                    "system_tcc": {"hits": []},
                    "regdb": {"hits": []},
                },
            ),
            Observation(
                collector="launchservices",
                started_at=1,
                ended_at=2,
                payload={
                    "stale_entries": [
                        {"bundle_id": "com.google.Chrome", "path": "/Volumes/OldDisk/Google Chrome.app"},
                        {"bundle_id": "com.google.Chrome.code_sign_clone", "path": "/Applications/Google Chrome.app"},
                    ],
                    "candidate_files": {"stdout": "/System/Library/LaunchServices/com.apple.LaunchServices.csstore\n"},
                },
            ),
        ],
    )


def test_solver_exposes_rule_explanations_for_complex_evidence():
    trace_analysis = {
        "signal_counts": {
            "securityprivacyextension": 2,
            "launchservices_csstore": 3,
            "chrome_code_sign_clone": 2,
        }
    }

    solution = build_local_network_solution(_snapshot_with_complex_evidence(), trace_analysis=trace_analysis)

    assert solution.rule_matches
    assert {match.rule_id for match in solution.rule_matches} >= {
        "ln-rule-chrome-identity-reinstall",
        "ln-rule-trace-ui-correlation",
    }
    rendered = solution.render_text()
    assert "Rule explanation" in rendered
    assert "ln-rule-chrome-identity-reinstall" in rendered
    assert "Matched evidence: LN-E001, LN-E002, LN-E005, LN-E006, LN-E008" in rendered


def test_solver_rule_explanations_are_deterministic_when_collected_evidence_order_changes(monkeypatch):
    snapshot = _snapshot_with_complex_evidence()
    trace_analysis = {"signal_counts": {"chrome_code_sign_clone": 1, "launchservices_csstore": 1}}
    normal = build_local_network_solution(snapshot, trace_analysis=trace_analysis)

    from macos_state_explorer.solver import local_network as solver_module

    original_collect = solver_module.collect_local_network_evidence

    def reversed_collect(*args, **kwargs):
        return list(reversed(original_collect(*args, **kwargs)))

    monkeypatch.setattr(solver_module, "collect_local_network_evidence", reversed_collect)

    reversed_solution = build_local_network_solution(snapshot, trace_analysis=trace_analysis)

    assert [match.rule_id for match in normal.rule_matches] == [
        match.rule_id for match in reversed_solution.rule_matches
    ]
    assert normal.render_text().split("Rule explanation", 1)[1] == reversed_solution.render_text().split(
        "Rule explanation", 1
    )[1]
