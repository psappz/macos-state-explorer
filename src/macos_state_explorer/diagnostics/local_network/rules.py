from __future__ import annotations

from macos_state_explorer.diagnostics.rules import DiagnosticRule

LOCAL_NETWORK_RULES = (
    DiagnosticRule(
        id="ln-rule-trash-launchservices",
        diagnosis_id="trashed-chrome-launchservices-registration",
        required_evidence=("LN-E007",),
        optional_evidence=("LN-E002", "LN-E003", "LN-E006"),
        confidence=0.55,
        repair_recommendations=("manual-empty-trash-reboot", "manual-reinstall-chrome", "trace-local-network"),
        explanation="A stale Chrome/Google LaunchServices registration points inside Trash; only then is manual Empty Trash ranked first.",
        priority=10,
    ),
    DiagnosticRule(
        id="ln-rule-chrome-identity-reinstall",
        diagnosis_id="chrome-identity-registration",
        required_evidence=("LN-E006",),
        optional_evidence=("LN-E001", "LN-E002", "LN-E005", "LN-E008"),
        confidence=0.45,
        repair_recommendations=("manual-reinstall-chrome", "trace-local-network"),
        explanation="Chrome code-sign-clone identity evidence indicates that a fresh signed Chrome registration is the next safest repair branch.",
        priority=20,
    ),
    DiagnosticRule(
        id="ln-rule-non-trash-launchservices",
        diagnosis_id="chrome-identity-registration",
        required_evidence=("LN-E008",),
        optional_evidence=("LN-E001", "LN-E002", "LN-E003"),
        confidence=0.35,
        repair_recommendations=("manual-reinstall-chrome", "trace-local-network"),
        explanation="Stale Chrome/Google LaunchServices evidence exists outside Trash, so reinstall is safer than emptying Trash.",
        priority=30,
    ),
    DiagnosticRule(
        id="ln-rule-trace-ui-correlation",
        diagnosis_id="privacy-ui-trace-correlation",
        required_evidence=("LN-E004",),
        optional_evidence=("LN-E001", "LN-E005", "LN-E009"),
        confidence=0.3,
        repair_recommendations=("trace-local-network", "manual-reinstall-chrome"),
        explanation="SecurityPrivacyExtension trace evidence ties the Local Network UI path to captured trace signals.",
        priority=40,
    ),
)
