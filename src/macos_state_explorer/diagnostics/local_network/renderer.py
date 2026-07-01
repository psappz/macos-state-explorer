from __future__ import annotations

from macos_state_explorer.diagnostics.local_network.models import DiagnosticStep, LocalNetworkDiagnosis


def render_terminal_report(diagnosis: LocalNetworkDiagnosis) -> str:
    lines = [
        "Local Network Diagnosis",
        "",
        f"1. Diagnosis: {diagnosis.diagnosis}",
        f"2. Confidence: {diagnosis.confidence:.0%}",
        f"3. Most likely cause: {diagnosis.most_likely_cause}",
        "4. Evidence:",
    ]
    if diagnosis.evidence:
        for finding in diagnosis.evidence:
            lines.append(f"   - {finding.title} ({finding.severity}, {finding.confidence:.0%}): {finding.summary}")
    else:
        lines.append("   - No evidence items found in the fast snapshot.")

    lines.extend(
        [
            f"5. Recommended next action: {diagnosis.recommended_next_action.title}",
            f"   {diagnosis.recommended_next_action.description}",
            f"6. Risk: {diagnosis.risk}",
            f"7. Expected result: {diagnosis.expected_result}",
            f"8. Verification command: {diagnosis.verification.command}",
            f"   Expected: {diagnosis.verification.expected_result}",
            "9. Fallback path if unsuccessful:",
        ]
    )
    if diagnosis.fallback_path:
        for step in diagnosis.fallback_path:
            lines.extend(_render_step(step))
    else:
        lines.append("   - No fallback path is recommended yet.")
    return "\n".join(lines)


def _render_step(step: DiagnosticStep) -> list[str]:
    lines = [f"   - {step.title} ({step.risk}, {step.mode}): {step.description}"]
    for command in step.commands:
        lines.append(f"     $ {command}")
    lines.append(f"     Expected: {step.expected_result}")
    return lines
