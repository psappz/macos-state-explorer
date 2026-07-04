from __future__ import annotations

from macos_state_explorer.diagnostics.local_network.evidence import LocalNetworkEvidence
from macos_state_explorer.diagnostics.rules import DiagnosticRule, RuleEngine


def _evidence(*ids: str) -> list[LocalNetworkEvidence]:
    return [
        LocalNetworkEvidence(
            id=evidence_id,
            title=f"Evidence {evidence_id}",
            detail="present",
            source="test",
            present=True,
        )
        for evidence_id in ids
    ]


def test_rule_requires_all_required_evidence_and_rejects_conflicts():
    rule = DiagnosticRule(
        id="rule-trash-ls",
        diagnosis_id="launchservices-trash-registration",
        required_evidence=("LN-E002", "LN-E007"),
        conflicting_evidence=("LN-E010",),
        confidence=0.42,
        repair_recommendations=("manual-empty-trash-reboot",),
        explanation="Trash-specific LaunchServices evidence is present.",
    )

    assert not RuleEngine([rule]).evaluate(_evidence("LN-E002"))
    assert not RuleEngine([rule]).evaluate(_evidence("LN-E002", "LN-E007", "LN-E010"))

    matches = RuleEngine([rule]).evaluate(_evidence("LN-E002", "LN-E007"))

    assert [match.rule_id for match in matches] == ["rule-trash-ls"]
    assert matches[0].matched_required_evidence == ("LN-E002", "LN-E007")
    assert matches[0].matched_conflicting_evidence == ()
    assert matches[0].confidence_contribution == 0.42


def test_rule_records_optional_evidence_that_contributed_to_match():
    rule = DiagnosticRule(
        id="rule-reinstall-code-sign-clone",
        diagnosis_id="chrome-identity-registration",
        required_evidence=("LN-E006",),
        optional_evidence=("LN-E001", "LN-E005"),
        confidence=0.5,
        repair_recommendations=("manual-reinstall-chrome",),
        explanation="Chrome identity evidence points to a reinstall branch.",
    )

    matches = RuleEngine([rule]).evaluate(_evidence("LN-E006", "LN-E005"))

    assert matches[0].matched_required_evidence == ("LN-E006",)
    assert matches[0].matched_optional_evidence == ("LN-E005",)
    assert matches[0].evidence_ids == ("LN-E006", "LN-E005")


def test_multiple_rules_can_contribute_to_same_diagnosis():
    rules = [
        DiagnosticRule(
            id="rule-launchservices-stale",
            diagnosis_id="chrome-identity-registration",
            required_evidence=("LN-E008",),
            confidence=0.3,
            repair_recommendations=("manual-reinstall-chrome",),
            explanation="Non-Trash stale registration is present.",
        ),
        DiagnosticRule(
            id="rule-trace-code-sign-clone",
            diagnosis_id="chrome-identity-registration",
            required_evidence=("LN-E006",),
            optional_evidence=("LN-E005",),
            confidence=0.4,
            repair_recommendations=("manual-reinstall-chrome", "trace-local-network"),
            explanation="Trace shows Chrome code-sign-clone activity.",
        ),
    ]

    diagnosis = RuleEngine(rules).diagnose(_evidence("LN-E008", "LN-E006", "LN-E005"))

    assert list(diagnosis) == ["chrome-identity-registration"]
    aggregate = diagnosis["chrome-identity-registration"]
    assert [match.rule_id for match in aggregate.matches] == [
        "rule-launchservices-stale",
        "rule-trace-code-sign-clone",
    ]
    assert aggregate.confidence == 0.7
    assert aggregate.repair_recommendations == (
        "manual-reinstall-chrome",
        "trace-local-network",
    )
    assert aggregate.evidence_ids == ("LN-E008", "LN-E006", "LN-E005")


def test_rule_evaluation_is_deterministic_regardless_of_evidence_order():
    rules = [
        DiagnosticRule(
            id="b-rule",
            diagnosis_id="second",
            required_evidence=("LN-E005",),
            optional_evidence=("LN-E001",),
            confidence=0.2,
            repair_recommendations=("trace-local-network",),
            explanation="Trace evidence is present.",
        ),
        DiagnosticRule(
            id="a-rule",
            diagnosis_id="first",
            required_evidence=("LN-E002",),
            optional_evidence=("LN-E007",),
            confidence=0.2,
            repair_recommendations=("manual-empty-trash-reboot",),
            explanation="LaunchServices evidence is present.",
        ),
    ]
    forward = RuleEngine(rules).evaluate(_evidence("LN-E001", "LN-E002", "LN-E005", "LN-E007"))
    reversed_matches = RuleEngine(rules).evaluate(list(reversed(_evidence("LN-E001", "LN-E002", "LN-E005", "LN-E007"))))

    assert forward == reversed_matches
    assert [match.rule_id for match in forward] == ["a-rule", "b-rule"]
