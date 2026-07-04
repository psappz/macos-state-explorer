from __future__ import annotations

from macos_state_explorer.diagnostics.rules import DiagnosticRule

LAUNCHSERVICES_RULES = (
    DiagnosticRule(
        id="ls-rule-stale-and-missing-paths",
        diagnosis_id="launchservices-stale-registrations",
        required_evidence=("LS-E001", "LS-E002"),
        optional_evidence=("LS-E003", "LS-E004"),
        confidence=0.9,
        repair_recommendations=("review-stale-launchservices", "collect-launchservices-support-bundle"),
        explanation="Stale registrations with missing paths indicate LaunchServices is retaining app records that no longer resolve cleanly.",
        priority=10,
    ),
    DiagnosticRule(
        id="ls-rule-duplicate-bundle-identifiers",
        diagnosis_id="launchservices-duplicate-bundles",
        required_evidence=("LS-E003",),
        optional_evidence=("LS-E001", "LS-E002"),
        confidence=0.75,
        repair_recommendations=("review-duplicate-bundle-identifiers", "collect-launchservices-support-bundle"),
        explanation="Multiple registrations for the same bundle identifier can make LaunchServices choose an unexpected app record.",
        priority=20,
    ),
    DiagnosticRule(
        id="ls-rule-suspicious-candidate-files",
        diagnosis_id="launchservices-candidate-files-present",
        required_evidence=("LS-E004",),
        confidence=0.55,
        repair_recommendations=("collect-launchservices-support-bundle",),
        explanation="LaunchServices cache or candidate files are present and should be captured before proposing any cleanup.",
        priority=30,
    ),
)
