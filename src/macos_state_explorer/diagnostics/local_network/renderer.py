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
            "5. Historical observations:",
            f"   - LaunchServices stale/orphaned registrations: {diagnosis.historical_evidence.launchservices_stale_count}",
            f"   - Missing TCC Local Network rows: {diagnosis.historical_evidence.tcc_missing_localnetwork_rows}",
            "6. Current functional state:",
            f"   - Status: {diagnosis.functional_state.status}",
            f"   - Local Network UI: {diagnosis.functional_state.local_network_ui}",
            f"   - Chrome entries: {diagnosis.functional_state.chrome_entry_count if diagnosis.functional_state.chrome_entry_count is not None else 'unknown'}",
            f"   - Permission enabled: {diagnosis.functional_state.permission_enabled if diagnosis.functional_state.permission_enabled is not None else 'unknown'}",
            f"   - Communication: {diagnosis.functional_state.communication}",
            f"7. Current risk: {diagnosis.current_risk}",
            f"8. Conclusion: {diagnosis.conclusion or diagnosis.diagnosis}",
            f"9. Recommended next action: {diagnosis.recommended_next_action.title}",
            f"   {diagnosis.recommended_next_action.description}",
            f"10. Risk: {diagnosis.risk}",
            f"11. Expected result: {diagnosis.expected_result}",
            f"12. Verification command: {diagnosis.verification.command}",
            f"   Expected: {diagnosis.verification.expected_result}",
            "13. Fallback path if unsuccessful:",
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
