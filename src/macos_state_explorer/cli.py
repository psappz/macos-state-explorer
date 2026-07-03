from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stdout
from dataclasses import replace
from typing import Any
import io
import json as json_module
import subprocess
import typer
from rich.console import Console

from macos_state_explorer.collectors.launchservices import LaunchServicesCollector
from macos_state_explorer.core.snapshot import create_snapshot
from macos_state_explorer.core.util import write_json
from macos_state_explorer.diagnostics.framework import FrameworkDiagnosticEngine, RepairPlanStatus, RepairStatus, RepairVerification
from macos_state_explorer.diagnostics.local_network.engine import diagnose_local_network
from macos_state_explorer.diagnostics.local_network.module import LOCAL_NETWORK_MODULE
from macos_state_explorer.diagnostics.local_network.renderer import render_terminal_report
from macos_state_explorer.diagnostics.local_network.verification import render_verification_report, verify_local_network
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.experiments.local_network import experiment_local_network
from macos_state_explorer.launchservices.analysis import analysis_from_snapshot_payload, analysis_records_from_snapshot_payload, render_launchservices_analysis
from macos_state_explorer.launchservices.cleanup_checklist import build_launchservices_cleanup_checklist, render_launchservices_cleanup_checklist
from macos_state_explorer.launchservices.cleanup_verification import build_launchservices_cleanup_verification, render_launchservices_cleanup_verification
from macos_state_explorer.launchservices.generations import analyze_generations, render_generation_summary
from macos_state_explorer.launchservices.outcome import build_launchservices_outcome, read_execute_plan_audit_history, render_launchservices_outcome
from macos_state_explorer.launchservices.producer_evidence import build_launchservices_producer_evidence, render_launchservices_producer_evidence
from macos_state_explorer.launchservices.provenance import build_launchservices_provenance, render_launchservices_provenance
from macos_state_explorer.launchservices.regeneration import build_launchservices_regeneration, render_launchservices_regeneration
from macos_state_explorer.launchservices.remediation_plan import (
    LaunchServicesRemediationPlan,
    RemediationSafety,
    plan_launchservices_remediation,
    render_remediation_plan,
)
from macos_state_explorer.networkextension_candidate_validation import build_networkextension_candidate_validation, render_networkextension_candidate_validation
from macos_state_explorer.networkextension_correlation import build_networkextension_correlation, render_networkextension_correlation
from macos_state_explorer.networkextension_object_graph import build_networkextension_object_graph, render_networkextension_object_graph
from macos_state_explorer.networkextension_raw_references import build_networkextension_raw_references, render_networkextension_raw_references
from macos_state_explorer.networkextension_repair_candidates import build_networkextension_repair_candidates, render_networkextension_repair_candidates
from macos_state_explorer.networkextension_repair_plan_preview import build_networkextension_repair_plan_preview, render_networkextension_repair_plan_preview
from macos_state_explorer.networkextension_repair_transaction_package import build_networkextension_repair_transaction_package, render_networkextension_repair_transaction_package
from macos_state_explorer.networkextension_manual_repair_runbook import build_networkextension_manual_repair_runbook, render_networkextension_manual_repair_runbook
from macos_state_explorer.networkextension_repair_simulation import build_networkextension_repair_simulation, render_networkextension_repair_simulation
from macos_state_explorer.networkextension_repair_artifact import build_networkextension_repair_artifact, render_networkextension_repair_artifact
from macos_state_explorer.networkextension_apply_validation import validate_networkextension_apply, render_networkextension_apply_validation
from macos_state_explorer.networkextension_repair_apply import DEFAULT_ARTIFACT, DEFAULT_BACKUP_DIR, DEFAULT_METADATA, DEFAULT_TARGET, CONFIRMATION_STRING, apply_networkextension_repair_artifact, render_networkextension_repair_apply
from macos_state_explorer.networkextension_state import build_networkextension_state, default_networkextension_roots, render_networkextension_state
from macos_state_explorer.remediation.rules import build_remediation_plan
from macos_state_explorer.reports.html import write_report
from macos_state_explorer.reports.launchservices import build_launchservices_report, write_launchservices_support_bundle
from macos_state_explorer.reports.launchservices_html import write_launchservices_html
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle
from macos_state_explorer.solver.launchservices import build_launchservices_solution
from macos_state_explorer.solver.local_network import build_local_network_solution, load_trace_analysis
from macos_state_explorer.tracers.local_network import build_trace_timeline, render_trace_timeline, trace_json_payload, trace_local_network
from macos_state_explorer.trace_correlation import build_trace_correlation_evidence, render_trace_correlation_evidence

app = typer.Typer(no_args_is_help=True)
trace_app = typer.Typer(no_args_is_help=True)
experiment_app = typer.Typer(no_args_is_help=True)
diagnose_app = typer.Typer(no_args_is_help=True)
solve_app = typer.Typer(no_args_is_help=True)
verify_app = typer.Typer(no_args_is_help=True)
report_app = typer.Typer(no_args_is_help=True)
repair_app = typer.Typer(no_args_is_help=True)
diff_app = typer.Typer(no_args_is_help=True)
networkextension_app = typer.Typer(no_args_is_help=True)
app.add_typer(trace_app, name="trace")
app.add_typer(experiment_app, name="experiment")
app.add_typer(diagnose_app, name="diagnose")
app.add_typer(solve_app, name="solve")
app.add_typer(verify_app, name="verify")
app.add_typer(report_app, name="report")
app.add_typer(repair_app, name="repair")
app.add_typer(diff_app, name="diff")
app.add_typer(networkextension_app, name="networkextension")
console = Console()


@app.command()
def collect(out: Path, fast: bool = False):
    snap = create_snapshot(fast=fast)
    write_report(out.expanduser(), snap)
    console.print(f"[green]Report:[/green] {out.expanduser() / 'index.html'}")


@networkextension_app.command("state")
def networkextension_state_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only root or file to inspect. Repeatable; defaults to safe system preference locations."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    state = build_networkextension_state(roots)
    if json_output:
        typer.echo(json_module.dumps(state.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_state(state), markup=False)


@networkextension_app.command("correlate")
def networkextension_correlate_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    trace: Path | None = typer.Option(None, "--trace", help="Optional read-only Local Network trace analysis directory or JSON file."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    snap = create_snapshot(fast=True)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    records = analysis_records_from_snapshot_payload(payload)
    correlation = build_networkextension_correlation(
        analyze_generations(records),
        records,
        roots=roots,
        trace_analysis=load_trace_analysis(trace),
    )
    if json_output:
        typer.echo(json_module.dumps(correlation.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_correlation(correlation), markup=False)


@networkextension_app.command("raw-references")
def networkextension_raw_references_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    raw_references = build_networkextension_raw_references(roots)
    if json_output:
        typer.echo(json_module.dumps(raw_references.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_raw_references(raw_references), markup=False)


@networkextension_app.command("object-graph")
def networkextension_object_graph_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    object_graph = build_networkextension_object_graph(roots)
    if json_output:
        typer.echo(json_module.dumps(object_graph.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_object_graph(object_graph), markup=False)


@networkextension_app.command("repair-candidates")
def networkextension_repair_candidates_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    candidates = build_networkextension_repair_candidates(roots)
    if json_output:
        typer.echo(json_module.dumps(candidates.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_repair_candidates(candidates), markup=False)


@networkextension_app.command("validate-candidates")
def networkextension_validate_candidates_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    snap = create_snapshot(fast=True)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    validation = build_networkextension_candidate_validation(roots, launchservices_entries=payload.get("entries", []))
    if json_output:
        typer.echo(json_module.dumps(validation.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_candidate_validation(validation), markup=False)


@networkextension_app.command("repair-plan-preview")
def networkextension_repair_plan_preview_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    snap = create_snapshot(fast=True)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    validation = build_networkextension_candidate_validation(roots, launchservices_entries=payload.get("entries", []))
    preview = build_networkextension_repair_plan_preview(validation)
    if json_output:
        typer.echo(json_module.dumps(preview.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_repair_plan_preview(preview), markup=False)


@networkextension_app.command("repair-transaction-package")
def networkextension_repair_transaction_package_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    snap = create_snapshot(fast=True)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    validation = build_networkextension_candidate_validation(roots, launchservices_entries=payload.get("entries", []))
    preview = build_networkextension_repair_plan_preview(validation)
    package = build_networkextension_repair_transaction_package(preview, roots)
    if json_output:
        typer.echo(json_module.dumps(package.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_repair_transaction_package(package), markup=False)


@networkextension_app.command("manual-repair-runbook")
def networkextension_manual_repair_runbook_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    snap = create_snapshot(fast=True)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    validation = build_networkextension_candidate_validation(roots, launchservices_entries=payload.get("entries", []))
    preview = build_networkextension_repair_plan_preview(validation)
    package = build_networkextension_repair_transaction_package(preview, roots)
    runbook = build_networkextension_manual_repair_runbook(package, roots)
    if json_output:
        typer.echo(json_module.dumps(runbook.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_manual_repair_runbook(runbook), markup=False)


@networkextension_app.command("repair-simulation")
def networkextension_repair_simulation_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    snap = create_snapshot(fast=True)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    validation = build_networkextension_candidate_validation(roots, launchservices_entries=payload.get("entries", []))
    preview = build_networkextension_repair_plan_preview(validation)
    package = build_networkextension_repair_transaction_package(preview, roots)
    runbook = build_networkextension_manual_repair_runbook(package, roots)
    simulation = build_networkextension_repair_simulation(runbook, roots)
    if json_output:
        typer.echo(json_module.dumps(simulation.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_repair_simulation(simulation), markup=False)


@networkextension_app.command("generate-repair-artifact")
def networkextension_generate_repair_artifact_command(
    root: list[Path] | None = typer.Option(None, "--root", help="Read-only NetworkExtension root or file to inspect; repeatable."),
    output: Path = typer.Option(Path("networkextension-repair-artifact.plist"), "--output", help="Offline output plist path. Must not target live/protected system paths."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    roots = root if root else default_networkextension_roots()
    snap = create_snapshot(fast=True)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    validation = build_networkextension_candidate_validation(roots, launchservices_entries=payload.get("entries", []))
    preview = build_networkextension_repair_plan_preview(validation)
    package = build_networkextension_repair_transaction_package(preview, roots)
    runbook = build_networkextension_manual_repair_runbook(package, roots)
    simulation = build_networkextension_repair_simulation(runbook, roots)
    try:
        artifact = build_networkextension_repair_artifact(runbook, simulation, output, roots)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    metadata_output = output.with_suffix(".json")
    metadata_output.write_text(json_module.dumps(artifact.to_json_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if json_output:
        payload = artifact.to_json_dict()
        payload["metadata_sidecar_path"] = str(metadata_output)
        typer.echo(json_module.dumps(payload, sort_keys=False))
    else:
        console.print(render_networkextension_repair_artifact(artifact), markup=False)
        console.print(f"- Metadata sidecar: {metadata_output}", markup=False)


@networkextension_app.command("apply-repair-artifact")
def networkextension_apply_repair_artifact_command(
    artifact: Path = typer.Option(DEFAULT_ARTIFACT, "--artifact", help="Existing generated repair artifact plist to apply."),
    metadata: Path = typer.Option(DEFAULT_METADATA, "--metadata", help="JSON metadata produced with the generated artifact."),
    target: Path = typer.Option(DEFAULT_TARGET, "--target", help="Target plist. Must be exactly the protected NetworkExtension plist path."),
    backup_dir: Path = typer.Option(DEFAULT_BACKUP_DIR, "--backup-dir", help="User-controlled backup destination."),
    confirm_apply: str | None = typer.Option(None, "--confirm-apply", help=f"Dangerous confirmation string: {CONFIRMATION_STRING}"),
    protected_target: Path = typer.Option(DEFAULT_TARGET, "--protected-target", help="Expected protected target path; testing override for fixture roots."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    result = apply_networkextension_repair_artifact(
        artifact,
        metadata,
        target_path=target,
        backup_dir=backup_dir,
        confirm_apply=confirm_apply,
        protected_target=protected_target,
    )
    if json_output:
        typer.echo(json_module.dumps(result.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_repair_apply(result), markup=False)


@networkextension_app.command("apply-validation")
def networkextension_apply_validation_command(
    target: Path = typer.Option(DEFAULT_TARGET, "--target", help="Post-apply target plist to validate."),
    artifact: Path = typer.Option(DEFAULT_ARTIFACT, "--artifact", help="Generated repair artifact expected to match the target."),
    metadata: Path = typer.Option(DEFAULT_METADATA, "--metadata", help="JSON metadata produced with the generated artifact."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
):
    validation = validate_networkextension_apply(target, artifact, metadata_path=metadata)
    if json_output:
        typer.echo(json_module.dumps(validation.to_json_dict(), sort_keys=False))
    else:
        console.print(render_networkextension_apply_validation(validation), markup=False)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def launchservices(
    ctx: typer.Context,
    out: Path = typer.Argument(..., help="Output directory, or 'analyze' for root-cause analysis."),
):
    if str(out) in {"analyze", "generations", "plan", "execute-plan", "outcome", "provenance", "producer-evidence", "regeneration", "cleanup-checklist", "verify-cleanup"}:
        snap = create_snapshot(fast=True)
        payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
        payload = payload if isinstance(payload, dict) else {}
        if str(out) in {"generations", "plan", "execute-plan", "outcome", "provenance", "producer-evidence", "regeneration", "cleanup-checklist", "verify-cleanup"}:
            generations = analyze_generations(analysis_records_from_snapshot_payload(payload))
            if str(out) == "cleanup-checklist":
                trace_path = _option_path(ctx.args, "--trace")
                checklist = build_launchservices_cleanup_checklist(generations, trace_analysis=load_trace_analysis(trace_path))
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(checklist.to_json_dict(), sort_keys=False))
                else:
                    console.print(render_launchservices_cleanup_checklist(checklist), markup=False)
                return
            if str(out) == "verify-cleanup":
                verification = build_launchservices_cleanup_verification(generations)
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(verification.to_json_dict(), sort_keys=False))
                else:
                    console.print(render_launchservices_cleanup_verification(verification), markup=False)
                return
            if str(out) == "producer-evidence":
                trace_path = _option_path(ctx.args, "--trace")
                producer_evidence = build_launchservices_producer_evidence(snap, trace_analysis=load_trace_analysis(trace_path), trace_source=trace_path)
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(producer_evidence.to_json_dict(), sort_keys=False))
                else:
                    console.print(render_launchservices_producer_evidence(producer_evidence), markup=False)
                return
            if str(out) == "regeneration":
                trace_path = _option_path(ctx.args, "--trace")
                regeneration = build_launchservices_regeneration(
                    generations,
                    trace_analysis=load_trace_analysis(trace_path),
                    audit_history=read_execute_plan_audit_history(_option_paths(ctx.args, "--audit-log")),
                )
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(regeneration.to_json_dict(), sort_keys=False))
                else:
                    console.print(render_launchservices_regeneration(regeneration), markup=False)
                return
            if str(out) == "provenance":
                provenance = build_launchservices_provenance(generations)
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(provenance.to_json_dict(), sort_keys=False))
                else:
                    console.print(render_launchservices_provenance(provenance), markup=False)
                return
            if str(out) == "outcome":
                outcome = build_launchservices_outcome(generations, audit_history=read_execute_plan_audit_history(_option_paths(ctx.args, "--audit-log")))
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(outcome.to_json_dict(), sort_keys=False))
                else:
                    console.print(render_launchservices_outcome(outcome), markup=False)
                return
            if str(out) == "execute-plan":
                plan = plan_launchservices_remediation(generations)
                audit_log = _option_path(ctx.args, "--audit-log")
                if "--confirm" in ctx.args:
                    execution = _launchservices_execute_plan_confirm(plan, generations, audit_log=audit_log)
                    if "--json" in ctx.args:
                        typer.echo(json_module.dumps(execution, sort_keys=False))
                    else:
                        console.print(_render_launchservices_execute_plan_execution(execution), markup=False)
                    if execution["status"] != "MUTATED_AND_REMOVED":
                        raise typer.Exit(1)
                    return
                if "--dry-run" not in ctx.args:
                    typer.echo("LaunchServices execute-plan requires --dry-run or --confirm.")
                    raise typer.Exit(1)
                execution = _launchservices_execute_plan_dry_run(plan)
                if audit_log is not None:
                    _write_launchservices_execute_plan_audit(audit_log, execution)
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(execution, sort_keys=False))
                else:
                    console.print(_render_launchservices_execute_plan_dry_run(execution), markup=False)
                return
            if str(out) == "plan":
                plan = plan_launchservices_remediation(generations)
                if "--json" in ctx.args:
                    typer.echo(json_module.dumps(plan.to_json_dict(), sort_keys=False))
                else:
                    console.print(render_remediation_plan(plan), markup=False)
                return
            if "--json" in ctx.args:
                typer.echo(json_module.dumps(generations.to_json_dict(), sort_keys=False))
            else:
                console.print(render_generation_summary(generations), markup=False)
            return
        analysis = analysis_from_snapshot_payload(payload)
        if "--json" in ctx.args:
            typer.echo(json_module.dumps(analysis.to_json_dict(), sort_keys=False))
        else:
            console.print(render_launchservices_analysis(analysis, verbose="--verbose" in ctx.args), markup=False)
        return
    out = out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    obs = LaunchServicesCollector().collect()
    write_json(out / "launchservices.json", obs)
    write_launchservices_html(out, obs.payload)
    stale = obs.payload.get("stale_entries", [])
    write_json(out / "stale-launchservices.json", stale)
    console.print(f"[green]LaunchServices output:[/green] {out}")
    console.print(f"Stale entries: {len(stale)}")


def _launchservices_execute_plan_dry_run(plan: LaunchServicesRemediationPlan) -> dict[str, object]:
    return {
        "command": "launchservices execute-plan",
        "plan_id": plan.plan_id,
        "dry_run": True,
        "commands_executed": [],
        "product_family": plan.product_family,
        "active_generation": plan.active_generation,
        "candidate_generations": list(plan.candidate_generations),
        "skipped_generations": list(plan.skipped_generations),
        "safety_summary": dict(plan.safety_summary),
        "steps": [_execute_plan_step_json(step) for step in plan.steps],
        "verification_commands": list(plan.verification_commands),
        "warnings": list(plan.warnings),
        "message": "No commands were executed. Dry-run only; LaunchServices mutation is not implemented.",
    }


def _execute_plan_step_json(step) -> dict[str, object]:
    payload = step.to_json_dict()
    payload["executable"] = False
    payload["commands_executed"] = []
    payload["execution_status"] = _execute_plan_step_status(step.safety)
    return payload


def _execute_plan_step_status(safety: RemediationSafety) -> str:
    if safety == RemediationSafety.MANUAL_REVIEW_REQUIRED:
        return "manual-review-only; not executable in dry run"
    if safety == RemediationSafety.PLAN_ONLY_SAFE:
        return "PLAN_ONLY_SAFE candidate; execution is not implemented yet"
    return f"{safety.value}; not executable in dry run"


def _is_phase1_executable_step(step) -> bool:
    return step.safety == RemediationSafety.PLAN_ONLY_SAFE and step.product_family == "Google Chrome" and step.action == "plan_unregister_obsolete_generation"


def _non_executable_step_reason(step) -> str:
    if step.safety == RemediationSafety.MANUAL_REVIEW_REQUIRED:
        return "Manual review required"
    if step.safety == RemediationSafety.PLAN_ONLY_SAFE:
        return "Phase 1 executes only PLAN_ONLY_SAFE Google Chrome obsolete helper/framework generations."
    return "Blocked by LaunchServices execution safety policy"


def _launchservices_execute_plan_confirm(plan: LaunchServicesRemediationPlan, before_analysis, audit_log: Path | None = None) -> dict[str, object]:
    active_before = plan.active_generation
    before_generation_count = len(before_analysis.generations)
    current_analysis = before_analysis
    executed_steps: list[dict[str, object]] = []
    skipped_steps = [_skipped_execution_step(step, _non_executable_step_reason(step)) for step in plan.steps if not _is_phase1_executable_step(step)]
    skipped_steps.extend(_skipped_generation_execution_step(generation) for generation in plan.skipped_generations)
    commands_executed: list[list[str]] = []
    errors: list[str] = []
    status = "UNKNOWN"
    after_analysis = before_analysis

    for step in plan.steps:
        if not _is_phase1_executable_step(step):
            continue
        invariant_errors = _validate_step_invariants(step, current_analysis)
        if invariant_errors:
            status = "NO_MUTATION"
            verification = _verification_result(
                before_analysis=current_analysis,
                after_analysis=current_analysis,
                step=step,
                command_results=[],
                errors=invariant_errors,
            )
            executed_steps.append(_executed_step_result(step, [], verification, invariant_errors))
            errors.extend(invariant_errors)
            _write_launchservices_generation_audit(audit_log, plan.plan_id, executed_steps[-1])
            break
        command_results = []
        for command in _commands_for_step(step):
            result = _run_launchservices_command(command)
            command_results.append(result)
            commands_executed.append(command)
            if int(result.get("exit_code", 1)) != 0:
                errors.append(f"Command failed for {step.generation_id}: {result.get('stderr') or result.get('stdout') or result.get('exit_code')}")
                break
        if errors:
            after_analysis = current_analysis
        else:
            after_analysis = _fresh_launchservices_generation_analysis()
        verification_errors = list(errors)
        verification = _verification_result(
            before_analysis=current_analysis,
            after_analysis=after_analysis,
            step=step,
            command_results=command_results,
            errors=verification_errors,
        )
        step_result = _executed_step_result(step, command_results, verification, list(verification["errors"]))
        executed_steps.append(step_result)
        _write_launchservices_generation_audit(audit_log, plan.plan_id, step_result)
        if verification["result"] != "MUTATED_AND_REMOVED":
            status = str(verification["result"])
            errors.extend(error for error in verification["errors"] if error not in errors)
            break
        status = "MUTATED_AND_REMOVED"
        current_analysis = after_analysis

    if status == "MUTATED_AND_REMOVED":
        after_analysis = current_analysis
    generation_diff = _generation_diff(before_analysis, after_analysis, [str(step.get("generation_id")) for step in executed_steps if isinstance(step, dict)])
    execution = {
        "command": "launchservices execute-plan",
        "plan_id": plan.plan_id,
        "dry_run": False,
        "confirmed": True,
        "status": status,
        "final_verdict": status,
        "product_family": plan.product_family,
        "before_generation_count": before_generation_count,
        "after_generation_count": len(after_analysis.generations),
        "active_generation_before": active_before,
        "active_generation_after": plan_launchservices_remediation(after_analysis).active_generation,
        "generation_diff": generation_diff,
        "executed_steps": executed_steps,
        "skipped_steps": skipped_steps,
        "commands_executed": commands_executed,
        "verification_commands": list(plan.verification_commands),
        "warnings": list(plan.warnings),
        "errors": errors,
        "message": "Executed only PLAN_ONLY_SAFE LaunchServices generation steps and verified persistent removal." if status == "MUTATED_AND_REMOVED" else "Stopped immediately after mutation did not produce persistent LaunchServices removal.",
    }
    _write_launchservices_run_audit(audit_log, execution)
    return execution


def _fresh_launchservices_generation_analysis():
    snap = create_snapshot(fast=False)
    payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
    payload = payload if isinstance(payload, dict) else {}
    return analyze_generations(analysis_records_from_snapshot_payload(payload))


def _generation_diff(before_analysis, after_analysis, executed_generation_ids: list[str]) -> dict[str, object]:
    before_ids = {generation.generation_id for generation in before_analysis.generations}
    after_ids = {generation.generation_id for generation in after_analysis.generations}
    executed = sorted(set(executed_generation_ids))
    return {
        "removed": sorted(before_ids - after_ids),
        "added": sorted(after_ids - before_ids),
        "persisted": sorted(before_ids & after_ids),
        "regenerated": [generation_id for generation_id in executed if generation_id in after_ids],
        "unchanged": sorted(before_ids & after_ids),
        "still_present": [generation_id for generation_id in executed if generation_id in after_ids],
        "executed": executed,
    }


def _validate_step_invariants(step, analysis) -> list[str]:
    generation = next((item for item in analysis.generations if item.generation_id == step.generation_id), None)
    if generation is None:
        return [f"Generation {step.generation_id} no longer exists before execution."]
    errors: list[str] = []
    if generation.classification.value != "STALE":
        errors.append(f"Generation {step.generation_id} is no longer obsolete.")
    if generation.active:
        errors.append(f"Generation {step.generation_id} is active and cannot be executed.")
    planned_paths = sorted(registration["path"] for registration in step.target_registrations)
    current_paths = sorted(registration.path for registration in generation.registrations)
    if len(current_paths) != len(planned_paths):
        errors.append(f"Generation {step.generation_id} registration count changed before execution.")
    if current_paths != planned_paths:
        errors.append(f"Generation {step.generation_id} target registrations changed before execution.")
    return errors


def _commands_for_step(step) -> list[list[str]]:
    lsregister = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    return [[lsregister, "-u", registration["path"]] for registration in step.target_registrations if registration.get("path")]


def _run_launchservices_command(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {"command": command, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "errno": completed.returncode if completed.returncode else None, "osstatus": None}


def _verification_result(*, before_analysis, after_analysis, step, command_results: list[dict[str, object]], errors: list[str]) -> dict[str, object]:
    before_ids = {generation.generation_id for generation in before_analysis.generations}
    after_ids = {generation.generation_id for generation in after_analysis.generations}
    active_before = plan_launchservices_remediation(before_analysis).active_generation
    active_after = plan_launchservices_remediation(after_analysis).active_generation
    generation_removed = step.generation_id in before_ids and step.generation_id not in after_ids
    executed_generation_absent = step.generation_id not in after_ids
    generation_count_decreased = len(after_ids) < len(before_ids)
    active_generation_unchanged = active_before == active_after
    command_failed = any(int(result.get("exit_code", 1)) != 0 for result in command_results)
    commands_attempted = bool(command_results)
    mutation_result = _mutation_result_state(
        commands_attempted=commands_attempted,
        command_failed=command_failed,
        generation_removed=generation_removed,
        executed_generation_absent=executed_generation_absent,
    )
    before_solution = build_local_network_solution(_snapshot_from_analysis(before_analysis))
    after_solution = build_local_network_solution(_snapshot_from_analysis(after_analysis))
    before_steps = before_solution.to_json_dict().get("remediation_plan_summary", {}).get("step_count", 0)
    after_steps = after_solution.to_json_dict().get("remediation_plan_summary", {}).get("step_count", 0)
    local_network_evidence_improves_or_consistent = mutation_result == "MUTATED_AND_REMOVED" and int(after_steps) <= int(before_steps)
    verification_errors = list(errors)
    if mutation_result == "MUTATION_FAILED":
        verification_errors.append("LaunchServices mutation primitive returned a non-zero result.")
    elif mutation_result == "NO_MUTATION":
        verification_errors.append("No LaunchServices mutation primitive was attempted or no persistent mutation was detected.")
    elif mutation_result == "MUTATED_BUT_REGENERATED":
        verification_errors.append(f"Executed generation {step.generation_id} is still present in fresh LaunchServices analyzer output.")
    if not active_generation_unchanged:
        verification_errors.append("Active generation changed after mutation.")
    return {
        "result": mutation_result,
        "before_generation_count": len(before_ids),
        "after_generation_count": len(after_ids),
        "generation_count_decreased": generation_count_decreased,
        "active_generation_unchanged": active_generation_unchanged,
        "generation_removed": generation_removed,
        "executed_generation_absent": executed_generation_absent,
        "regeneration_source": "fresh LaunchServices analysis still reports the executed generation" if mutation_result == "MUTATED_BUT_REGENERATED" else None,
        "local_network_evidence": "consistent" if local_network_evidence_improves_or_consistent else "unchanged-or-blocked",
        "local_network_evidence_improves_or_consistent": local_network_evidence_improves_or_consistent,
        "errors": verification_errors,
    }


def _mutation_result_state(*, commands_attempted: bool, command_failed: bool, generation_removed: bool, executed_generation_absent: bool) -> str:
    if command_failed:
        return "MUTATION_FAILED"
    if not commands_attempted:
        return "NO_MUTATION"
    if generation_removed and executed_generation_absent:
        return "MUTATED_AND_REMOVED"
    if not executed_generation_absent:
        return "MUTATED_BUT_REGENERATED"
    return "UNKNOWN"


def _snapshot_from_analysis(analysis):
    from macos_state_explorer.core.model import Observation, Snapshot

    return Snapshot(
        host="launchservices-execute-plan-verification",
        created_at=0,
        observations=[
            Observation(
                collector="launchservices",
                started_at=0,
                ended_at=0,
                payload={"entries": [registration.to_json_dict() for generation in analysis.generations for registration in generation.registrations]},
            )
        ],
    )


def _executed_step_result(step, command_results: list[dict[str, object]], verification: dict[str, object], errors: list[str]) -> dict[str, object]:
    registration_ids = [registration["path"] for registration in step.target_registrations]
    commands = [result["command"] for result in command_results]
    mutation_primitives = [_mutation_primitive_from_result(result, registration_ids) for result in command_results]
    return {
        "step_id": step.step_id,
        "generation_id": step.generation_id,
        "registration_ids": registration_ids,
        "registration_count": len(registration_ids),
        "safety": step.safety.value,
        "mutation_performed": bool(commands),
        "mutation_result": verification["result"],
        "mutation_primitives": mutation_primitives,
        "commands": commands,
        "verification": verification,
        "result": verification["result"],
        "errors": errors,
        "rollback_metadata": "Re-register affected application bundle manually or restore LaunchServices database from system backup if needed.",
    }


def _mutation_primitive_from_result(result: dict[str, object], registration_ids: list[str]) -> dict[str, object]:
    command = result.get("command") if isinstance(result.get("command"), list) else []
    return {
        "api": "lsregister",
        "command": command,
        "file": command[-1] if command else None,
        "launchservices_call": "unregister",
        "return_value": result.get("exit_code"),
        "errno": result.get("errno", result.get("exit_code") if result.get("exit_code") else None),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "osstatus": result.get("osstatus"),
        "affected_registration_ids": registration_ids,
    }


def _skipped_execution_step(step, reason: str) -> dict[str, object]:
    return {
        "step_id": step.step_id,
        "generation_id": step.generation_id,
        "registration_ids": [registration["path"] for registration in step.target_registrations],
        "registration_count": len(step.target_registrations),
        "safety": step.safety.value,
        "result": "NOT_EXECUTED",
        "reason": reason,
    }


def _skipped_generation_execution_step(generation: dict[str, object]) -> dict[str, object]:
    return {
        "step_id": None,
        "generation_id": generation["generation_id"],
        "registration_ids": [],
        "registration_count": generation.get("registration_count", 0),
        "safety": generation["safety"],
        "result": "NOT_EXECUTED",
        "reason": generation["reason"],
    }


def _write_launchservices_generation_audit(path: Path | None, plan_id: str, step_result: dict[str, object]) -> None:
    if path is None:
        return
    event = {
        "event": "launchservices_execute_plan_generation",
        "command": "launchservices execute-plan",
        "plan_id": plan_id,
        "generation_id": step_result["generation_id"],
        "registration_ids": step_result["registration_ids"],
        "mutation_primitives": step_result["mutation_primitives"],
        "commands": step_result["commands"],
        "verification": step_result["verification"],
        "before_generation_count": step_result["verification"]["before_generation_count"],
        "after_generation_count": step_result["verification"]["after_generation_count"],
        "errors": step_result["errors"],
        "rollback_metadata": step_result["rollback_metadata"],
    }
    _append_jsonl_audit_event(path, event)


def _write_launchservices_run_audit(path: Path | None, execution: dict[str, object]) -> None:
    if path is None:
        return
    event = {
        "event": "launchservices_execute_plan_run",
        "command": "launchservices execute-plan",
        "plan_id": execution["plan_id"],
        "confirmed": execution["confirmed"],
        "status": execution["status"],
        "final_verdict": execution["final_verdict"],
        "before_generation_count": execution["before_generation_count"],
        "after_generation_count": execution["after_generation_count"],
        "generation_diff": execution["generation_diff"],
        "executed_step_count": len(execution.get("executed_steps", [])) if isinstance(execution.get("executed_steps"), list) else 0,
        "skipped_step_count": len(execution.get("skipped_steps", [])) if isinstance(execution.get("skipped_steps"), list) else 0,
        "commands_executed": execution["commands_executed"],
        "errors": execution["errors"],
    }
    _append_jsonl_audit_event(path, event)


def _append_jsonl_audit_event(path: Path, event: dict[str, object]) -> None:
    expanded = path.expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    with expanded.open("a") as handle:
        handle.write(json_module.dumps(event, sort_keys=False) + "\n")


def _render_launchservices_execute_plan_execution(execution: dict[str, object]) -> str:
    lines = [
        "LaunchServices execute-plan execution",
        "",
        f"Plan ID: {execution['plan_id']}",
        f"Result: {execution['status']}",
        f"Final verdict: {execution['final_verdict']}",
        f"Before generation count: {execution['before_generation_count']}",
        f"After generation count: {execution['after_generation_count']}",
        "",
        "Mutation",
        "↓",
        "Fresh analysis",
        "↓",
        "Generation diff",
    ]
    diff = execution.get("generation_diff") if isinstance(execution.get("generation_diff"), dict) else {}
    for label, key in [("Removed", "removed"), ("Added", "added"), ("Persisted", "persisted"), ("Regenerated", "regenerated"), ("Still present", "still_present")]:
        values = diff.get(key, []) if isinstance(diff, dict) else []
        lines.append(f"- {label}: {', '.join(values) if values else 'none'}")
    lines.extend(["↓", "Evidence diff", "- Local Network evidence: gated by persistent generation removal"])
    lines.extend(["", "Executed steps"])
    for step in execution.get("executed_steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(f"- Generation: {step['generation_id']}")
        lines.append(f"  Registration count: {step['registration_count']}")
        lines.append(f"  Mutation performed: {step['mutation_performed']}")
        lines.append(f"  Verification: {step['verification']['result']}")
        lines.append(f"  Result: {step['result']}")
    if not execution.get("executed_steps"):
        lines.append("- none")
    lines.extend(["", "Skipped"])
    for step in execution.get("skipped_steps", []):
        if not isinstance(step, dict):
            continue
        reason = "Manual review required" if step.get("safety") == RemediationSafety.MANUAL_REVIEW_REQUIRED.value else step.get("reason")
        lines.append(f"- {step['generation_id']}: NOT EXECUTED — {reason}")
        for registration_id in step.get("registration_ids", []):
            lines.append(f"  - {registration_id}")
    if not execution.get("skipped_steps"):
        lines.append("- none")
    if execution.get("errors"):
        lines.extend(["", "Errors"])
        for error in execution["errors"]:
            lines.append(f"- {error}")
    return "\n".join(lines)


def _render_launchservices_execute_plan_dry_run(execution: dict[str, object]) -> str:
    lines = [
        "LaunchServices execute-plan dry run",
        "",
        f"Plan ID: {execution['plan_id']}",
        "dry_run: yes",
        f"Product family: {execution['product_family']}",
        "No commands were executed.",
    ]
    active = execution.get("active_generation")
    lines.extend(["", "Active generation:"])
    if isinstance(active, dict) and active.get("by_product"):
        for product, info in sorted(active["by_product"].items()):
            lines.append(f"- {product}: {info.get('version') or '<unknown>'} ({info.get('generation_id')})")
    else:
        lines.append("- none detected")
    lines.extend(["", "Candidate generations"])
    for candidate in execution.get("candidate_generations", []):
        if isinstance(candidate, dict):
            lines.append(f"- {candidate['product_family']} {candidate['generation_id']} — {candidate['safety']}: {candidate['reason']}")
    if not execution.get("candidate_generations"):
        lines.append("- none")
    lines.extend(["", "Skipped generations"])
    for skipped in execution.get("skipped_generations", []):
        if isinstance(skipped, dict):
            lines.append(f"- {skipped['product_family']} {skipped['generation_id']} — {skipped['safety']}: {skipped['reason']}")
    if not execution.get("skipped_generations"):
        lines.append("- none")
    lines.extend(["", "Planned steps"])
    for step in execution.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(f"- {step['step_id']}: {step['product_family']} {step['generation_id']}")
        lines.append(f"  Safety: {step['safety']}")
        lines.append(f"  Executable in future: {'yes' if step.get('executable') else 'no'}")
        lines.append(f"  Execution status: {step['execution_status']}")
        lines.append(f"  Expected effect: {step['expected_effect']}")
    if not execution.get("steps"):
        lines.append("- none")
    lines.extend(["", "Verification commands"])
    for command in execution.get("verification_commands", []):
        lines.append(f"- {command}")
    lines.extend(["", "Warnings"])
    for warning in execution.get("warnings", []):
        lines.append(f"- {warning}")
    lines.append("- No commands were executed. Dry-run only; LaunchServices mutation is not implemented.")
    return "\n".join(lines)


def _write_launchservices_execute_plan_audit(path: Path, execution: dict[str, object]) -> None:
    event = {
        "event": "launchservices_execute_plan_dry_run",
        "command": "launchservices execute-plan",
        "plan_id": execution["plan_id"],
        "dry_run": True,
        "commands_executed": [],
        "step_count": len(execution.get("steps", [])),
        "safety_summary": execution["safety_summary"],
        "message": execution["message"],
    }
    expanded = path.expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    with expanded.open("a") as handle:
        handle.write(json_module.dumps(event, sort_keys=False) + "\n")


def _option_path(args: list[str], name: str) -> Path | None:
    paths = _option_paths(args, name)
    return paths[0] if paths else None


def _option_paths(args: list[str], name: str) -> list[Path] | None:
    paths: list[Path] = []
    for index, value in enumerate(args):
        if value == name and index + 1 < len(args):
            paths.append(Path(args[index + 1]))
    return paths or None


@trace_app.command("local-network")
def trace_local_network_cmd(
    out: Path,
    seconds: int | None = None,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    if json_output:
        with redirect_stdout(io.StringIO()):
            analysis = trace_local_network(out.expanduser(), seconds=seconds)
        typer.echo(json_module.dumps(trace_json_payload(out.expanduser(), analysis), sort_keys=False))
    else:
        trace_local_network(out.expanduser(), seconds=seconds)


@trace_app.command("correlate")
def trace_correlate_cmd(
    trace: Path,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    evidence = build_trace_correlation_evidence(load_trace_analysis(trace), trace_source=trace)
    if json_output:
        typer.echo(json_module.dumps(evidence.to_json_dict(), sort_keys=False))
    else:
        console.print(render_trace_correlation_evidence(evidence), markup=False)


@trace_app.command("timeline")
def trace_timeline_cmd(
    trace: Path,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    timeline = build_trace_timeline(load_trace_analysis(trace))
    if json_output:
        typer.echo(json_module.dumps(timeline.to_json_dict(), sort_keys=False))
    else:
        console.print(render_trace_timeline(timeline), markup=False, soft_wrap=True)


@experiment_app.command("local-network")
def experiment_local_network_cmd(out: Path):
    experiment_local_network(out.expanduser())


@diagnose_app.command("local-network")
def diagnose_local_network_cmd():
    snap = create_snapshot(fast=True)
    diagnosis = diagnose_local_network(snap)
    console.print(render_terminal_report(diagnosis))


@solve_app.command("local-network")
def solve_local_network_cmd(
    trace: Path | None = None,
    audit_log: list[Path] | None = typer.Option(None, "--audit-log", help="Read LaunchServices execute-plan audit JSONL for outcome history; may be repeated."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    snap = create_snapshot(fast=True)
    solution = build_local_network_solution(snap, trace_analysis=load_trace_analysis(trace), launchservices_audit_log=audit_log)
    if json_output:
        typer.echo(json_module.dumps(solution.to_json_dict(), sort_keys=False))
    else:
        console.print(solution.render_text(), markup=False)


@solve_app.command("launchservices")
def solve_launchservices_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    snap = create_snapshot(fast=True)
    solution = build_launchservices_solution(snap)
    if json_output:
        typer.echo(json_module.dumps(solution.to_json_dict(), sort_keys=False))
    else:
        console.print(solution.render_text(), markup=False)


@verify_app.command("local-network")
def verify_local_network_cmd(
    branch: str = "manual-empty-trash-reboot",
    trace: Path | None = None,
    failed_branch: list[str] | None = typer.Option(
        None,
        "--failed-branch",
        help="Branch/action id that already failed in this workflow; may be repeated.",
    ),
    audit_log: Path | None = typer.Option(None, "--audit-log", help="Read failed branch/action ids from a repair audit JSONL log."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    snap = create_snapshot(fast=True)
    audit_failed_branches, _audit_failed_actions = _failed_history_from_repair_audit(audit_log)
    failed_branches = set(failed_branch or []) | audit_failed_branches
    result = verify_local_network(
        snap,
        expected_branch_id=branch,
        trace_analysis=load_trace_analysis(trace),
        failed_branches=failed_branches,
    )
    if json_output:
        typer.echo(json_module.dumps(result.to_json_dict(), sort_keys=False))
    else:
        console.print(render_verification_report(result), markup=False)


@repair_app.command("local-network")
def repair_local_network_cmd(
    action: str | None = typer.Option(None, "--action", help="Executable repair action id."),
    branch: str | None = typer.Option(None, "--branch", help="Repair candidate/branch id to repair."),
    trace: Path | None = None,
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Preview or execute the selected repair action."),
    confirm: bool = typer.Option(False, "--confirm", help="Required with --execute to run repair commands."),
    audit_log: Path | None = typer.Option(None, "--audit-log", help="Append a JSONL repair audit event to this path."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    snap = create_snapshot(fast=True)
    context = {"trace_analysis": load_trace_analysis(trace)}
    effective_dry_run = False if confirm else dry_run
    engine = FrameworkDiagnosticEngine(_local_network_module_with_repair_verifier())
    if action is not None or branch is not None:
        result = engine.repair(
            snap,
            action_id=action,
            candidate_id=branch,
            dry_run=effective_dry_run,
            confirmed=confirm,
            audit_log=audit_log,
            context=context,
        )
        if json_output:
            typer.echo(json_module.dumps(result.to_json_dict(), sort_keys=False))
        else:
            console.print(result.render_text(), markup=False)
        if result.status in {RepairStatus.NOT_FOUND, RepairStatus.BLOCKED, RepairStatus.FAILED}:
            raise typer.Exit(1)
        return
    plan_result = engine.repair_plan(
        snap,
        dry_run=effective_dry_run,
        confirmed=confirm,
        audit_log=audit_log,
        context=context,
        snapshot_provider=lambda: create_snapshot(fast=True),
    )
    if json_output:
        typer.echo(json_module.dumps(plan_result.to_json_dict(), sort_keys=False))
    else:
        console.print(plan_result.render_text(), markup=False)
    if plan_result.status in {RepairPlanStatus.BLOCKED, RepairPlanStatus.FAILED}:
        raise typer.Exit(1)


def _local_network_module_with_repair_verifier():
    return replace(LOCAL_NETWORK_MODULE, repair_verifier=_verify_local_network_repair_step)


def _failed_history_from_repair_audit(audit_log: Path | None) -> tuple[set[str], set[str]]:
    if audit_log is None:
        return set(), set()
    expanded = audit_log.expanduser()
    if not expanded.exists():
        return set(), set()
    failed_candidates: set[str] = set()
    failed_actions: set[str] = set()
    for line in expanded.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json_module.loads(line)
        except json_module.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        result = event.get("result", {})
        selected_action = event.get("selected_action", {})
        if isinstance(result, dict) and result.get("status") == "FAILED":
            _record_failed_candidate_id(result.get("candidate_id"), failed_candidates)
            if isinstance(selected_action, dict):
                _record_failed_candidate_id(selected_action.get("candidate_id"), failed_candidates)
            _record_failed_action_id(result.get("action_id"), failed_actions)
        if not isinstance(result, dict):
            continue
        for step in result.get("step_results", []):
            if not isinstance(step, dict):
                continue
            verification = step.get("verification")
            repair_result = step.get("repair_result")
            step_failed = step.get("status") == "FAILED"
            verification_failed = isinstance(verification, dict) and verification.get("status") == "FAILED"
            repair_failed = isinstance(repair_result, dict) and repair_result.get("status") == "FAILED"
            if step_failed or verification_failed or repair_failed:
                _record_failed_candidate_id(step.get("candidate_id"), failed_candidates)
                if isinstance(repair_result, dict):
                    _record_failed_candidate_id(repair_result.get("candidate_id"), failed_candidates)
                _record_failed_action_id(step.get("action_id"), failed_actions)
                if isinstance(repair_result, dict):
                    _record_failed_action_id(repair_result.get("action_id"), failed_actions)
    return failed_candidates, failed_actions


def _record_failed_candidate_id(value: object, failed_candidates: set[str]) -> None:
    if isinstance(value, str) and value:
        failed_candidates.add(value)


def _record_failed_action_id(value: object, failed_actions: set[str]) -> None:
    if isinstance(value, str) and value:
        failed_actions.add(value)


def _verify_local_network_repair_step(snapshot, candidate, context=None) -> RepairVerification:
    context = context or {}
    trace_analysis = context.get("trace_analysis")
    verification = verify_local_network(
        snapshot,
        expected_branch_id=candidate.id,
        trace_analysis=trace_analysis if isinstance(trace_analysis, dict) else None,
        failed_branches=set(context.get("failed_branches", [])),
    )
    return RepairVerification(
        status=verification.status,
        branch_id=verification.branch_id,
        observed_result=verification.observed_result,
        evidence_ids=list(verification.evidence_ids),
        continues_workflow=verification.continues_workflow,
        transition=verification.transition,
        next_step=verification.next_step,
    )


def _diff_support_bundles(before: Path, after: Path) -> dict[str, Any]:
    before_path = before.expanduser()
    after_path = after.expanduser()
    before_report = _read_bundle_report(before_path)
    after_report = _read_bundle_report(after_path)
    before_files = _bundle_file_set(before_path)
    after_files = _bundle_file_set(after_path)
    before_evidence = _evidence_presence_by_id(before_report)
    after_evidence = _evidence_presence_by_id(after_report)
    changed_fields = [field for field in ["diagnosis", "remediation_plan_summary", "verification", "generation_diff", "launchservices_outcome_summary", "launchservices_provenance_summary", "launchservices_producer_evidence_summary", "launchservices_regeneration_summary", "launchservices_cleanup_checklist_summary", "launchservices_cleanup_verification_summary", "networkextension_state_summary", "networkextension_correlation_summary", "networkextension_raw_references_summary", "networkextension_object_graph_summary", "networkextension_repair_candidates_summary", "networkextension_candidate_validation_summary", "networkextension_repair_plan_preview_summary", "networkextension_repair_transaction_package_summary", "networkextension_manual_repair_runbook_summary", "networkextension_repair_simulation_summary", "networkextension_repair_artifact_summary", "networkextension_repair_apply_summary", "trace_correlation_summary", "trace_timeline_summary"] if before_report.get(field) != after_report.get(field)]
    return {
        "command": "diff bundles",
        "before": {"path": str(before_path), "command": _read_json_if_exists(before_path / "command.json").get("command")},
        "after": {"path": str(after_path), "command": _read_json_if_exists(after_path / "command.json").get("command")},
        "files": {
            "added": sorted(after_files - before_files),
            "removed": sorted(before_files - after_files),
            "common": sorted(before_files & after_files),
        },
        "evidence_diff": {
            "added": sorted(set(after_evidence) - set(before_evidence)),
            "removed": sorted(set(before_evidence) - set(after_evidence)),
            "unchanged": sorted(set(before_evidence) & set(after_evidence)),
            "changed_presence": sorted(evidence_id for evidence_id in set(before_evidence) & set(after_evidence) if before_evidence[evidence_id] != after_evidence[evidence_id]),
        },
        "generation_diff": _bundle_generation_diff(before_report, after_report),
        "outcome_diff": _bundle_outcome_diff(before_report, after_report),
        "provenance_diff": _bundle_provenance_diff(before_report, after_report),
        "producer_evidence_diff": _bundle_producer_evidence_diff(before_report, after_report),
        "regeneration_diff": _bundle_regeneration_diff(before_report, after_report),
        "cleanup_checklist_diff": _bundle_cleanup_checklist_diff(before_report, after_report),
        "cleanup_verification_diff": _bundle_cleanup_verification_diff(before_report, after_report),
        "networkextension_state_diff": _bundle_networkextension_state_diff(before_report, after_report),
        "networkextension_correlation_diff": _bundle_networkextension_correlation_diff(before_report, after_report),
        "networkextension_raw_references_diff": _bundle_networkextension_raw_references_diff(before_report, after_report),
        "networkextension_object_graph_diff": _bundle_networkextension_object_graph_diff(before_report, after_report),
        "networkextension_repair_candidate_diff": _bundle_networkextension_repair_candidate_diff(before_report, after_report),
        "networkextension_candidate_validation_diff": _bundle_networkextension_candidate_validation_diff(before_report, after_report),
        "networkextension_repair_plan_preview_diff": _bundle_networkextension_repair_plan_preview_diff(before_report, after_report),
        "networkextension_repair_transaction_package_diff": _bundle_networkextension_repair_transaction_package_diff(before_report, after_report),
        "networkextension_manual_repair_runbook_diff": _bundle_networkextension_manual_repair_runbook_diff(before_report, after_report),
        "networkextension_repair_simulation_diff": _bundle_networkextension_repair_simulation_diff(before_report, after_report),
        "networkextension_repair_artifact_diff": _bundle_networkextension_repair_artifact_diff(before_report, after_report),
        "networkextension_repair_apply_diff": _bundle_networkextension_repair_apply_diff(before_report, after_report),
        "networkextension_apply_validation_diff": _bundle_networkextension_apply_validation_diff(before_report, after_report),
        "trace_correlation_diff": _bundle_trace_correlation_diff(before_report, after_report),
        "trace_timeline_diff": _bundle_trace_timeline_diff(before_report, after_report),
        "changed_fields": changed_fields,
    }


def _read_bundle_report(path: Path) -> dict[str, Any]:
    report_path = path / "report.json"
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Support bundle does not exist or is not a directory: {path}")
    if not report_path.exists():
        raise ValueError(f"Support bundle is missing report.json: {path}")
    payload = json_module.loads(report_path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Support bundle report.json is not an object: {path}")
    return payload


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json_module.loads(path.read_text())
    return payload if isinstance(payload, dict) else {}


def _bundle_file_set(path: Path) -> set[str]:
    return {str(item.relative_to(path)) for item in path.rglob("*") if item.is_file()}


def _evidence_presence_by_id(report: dict[str, Any]) -> dict[str, bool]:
    evidence = report.get("evidence")
    result: dict[str, bool] = {}
    if not isinstance(evidence, list):
        return result
    for item in evidence:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result[item["id"]] = bool(item.get("present", True))
    return result


def _bundle_generation_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, list[str]]:
    after = after_report.get("generation_diff") if isinstance(after_report.get("generation_diff"), dict) else {}
    return {
        "removed": _sorted_string_list(after.get("removed")),
        "added": _sorted_string_list(after.get("added")),
        "persisted": _sorted_string_list(after.get("persisted", after.get("unchanged"))),
        "regenerated": _sorted_string_list(after.get("regenerated", after.get("still_present"))),
    }


def _bundle_outcome_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("launchservices_outcome_summary")
    after_value = after_report.get("launchservices_outcome_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    return {
        "completed": int(after.get("completed", 0)) - int(before.get("completed", 0)),
        "remaining": int(after.get("remaining", 0)) - int(before.get("remaining", 0)),
        "newly_blocked": max(0, int(after.get("blocked", 0)) - int(before.get("blocked", 0))),
        "resolved": max(0, int(before.get("remaining", 0)) - int(after.get("remaining", 0))),
        "status_before": str(before.get("automatic_remediation_status", "UNKNOWN")),
        "status_after": str(after.get("automatic_remediation_status", "UNKNOWN")),
        "audit_informed_before": bool(before.get("audit_informed", False)),
        "audit_informed_after": bool(after.get("audit_informed", False)),
    }


def _bundle_provenance_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("launchservices_provenance_summary")
    after_value = after_report.get("launchservices_provenance_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_consumers = set(_sorted_string_list(before.get("consumers")))
    after_consumers = set(_sorted_string_list(after.get("consumers")))
    return {
        "producer_before": str(before.get("primary_producer", "Unknown")),
        "producer_after": str(after.get("primary_producer", "Unknown")),
        "persistence_before": str(before.get("persistence_source", "unknown")),
        "persistence_after": str(after.get("persistence_source", "unknown")),
        "added_consumers": sorted(after_consumers - before_consumers),
        "removed_consumers": sorted(before_consumers - after_consumers),
    }


def _bundle_producer_evidence_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("launchservices_producer_evidence_summary")
    after_value = after_report.get("launchservices_producer_evidence_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("observed_evidence_ids")))
    after_ids = set(_sorted_string_list(after.get("observed_evidence_ids")))
    before_conf = before.get("evidence_confidence") if isinstance(before.get("evidence_confidence"), dict) else {}
    after_conf = after.get("evidence_confidence") if isinstance(after.get("evidence_confidence"), dict) else {}
    before_status = before.get("observed_status") if isinstance(before.get("observed_status"), dict) else {}
    after_status = after.get("observed_status") if isinstance(after.get("observed_status"), dict) else {}
    common_conf = set(before_conf) & set(after_conf)
    common_status = set(before_status) & set(after_status)
    return {
        "added_evidence": sorted(after_ids - before_ids),
        "removed_evidence": sorted(before_ids - after_ids),
        "changed_confidence": sorted(key for key in common_conf if before_conf.get(key) != after_conf.get(key)),
        "changed_observed_status": sorted(key for key in common_status if before_status.get(key) != after_status.get(key)),
    }


def _bundle_regeneration_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("launchservices_regeneration_summary")
    after_value = after_report.get("launchservices_regeneration_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    return {
        "regenerator_before": str(before.get("top_regenerator", "Unknown")),
        "regenerator_after": str(after.get("top_regenerator", "Unknown")),
        "high_confidence_delta": int(after.get("high_confidence_generation_count", 0)) - int(before.get("high_confidence_generation_count", 0)),
        "unknown_delta": int(after.get("unknown_generation_count", 0)) - int(before.get("unknown_generation_count", 0)),
    }


def _bundle_cleanup_checklist_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("launchservices_cleanup_checklist_summary")
    after_value = after_report.get("launchservices_cleanup_checklist_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("item_ids")))
    after_ids = set(_sorted_string_list(after.get("item_ids")))
    common = before_ids & after_ids
    before_items_value = before.get("items")
    after_items_value = after.get("items")
    before_items = before_items_value if isinstance(before_items_value, dict) else {}
    after_items = after_items_value if isinstance(after_items_value, dict) else {}
    changed = sorted(item_id for item_id in common if before_items.get(item_id) != after_items.get(item_id))
    return {
        "added_item_ids": sorted(after_ids - before_ids),
        "removed_item_ids": sorted(before_ids - after_ids),
        "changed_item_ids": changed,
        "first_recommended_action_changed": before.get("first_recommended_manual_action") != after.get("first_recommended_manual_action"),
    }


def _bundle_cleanup_verification_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("launchservices_cleanup_verification_summary")
    after_value = after_report.get("launchservices_cleanup_verification_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_verified = set(_sorted_string_list(before.get("verified_item_ids")))
    after_verified = set(_sorted_string_list(after.get("verified_item_ids")))
    before_failed = set(_sorted_string_list(before.get("failed_item_ids")))
    after_failed = set(_sorted_string_list(after.get("failed_item_ids")))
    before_new = set(_sorted_string_list(before.get("newly_appeared_generation_ids")))
    after_new = set(_sorted_string_list(after.get("newly_appeared_generation_ids")))
    before_disappeared = set(_sorted_string_list(before.get("disappeared_generation_ids")))
    after_disappeared = set(_sorted_string_list(after.get("disappeared_generation_ids")))
    before_unchanged = set(_sorted_string_list(before.get("unchanged_generation_ids")))
    after_unchanged = set(_sorted_string_list(after.get("unchanged_generation_ids")))
    return {
        "verified_items": sorted(after_verified - before_verified),
        "failed_verification": sorted(after_failed - before_failed),
        "newly_appeared_generations": sorted(after_new - before_new),
        "disappeared_generations": sorted(after_disappeared - before_disappeared),
        "unchanged_generations": sorted(after_unchanged - before_unchanged),
    }


def _bundle_networkextension_state_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_state_summary")
    after_value = after_report.get("networkextension_state_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_artifacts = set(_sorted_string_list(before.get("artifact_paths")))
    after_artifacts = set(_sorted_string_list(after.get("artifact_paths")))
    before_bundle_ids = set(_sorted_string_list(before.get("bundle_ids")))
    after_bundle_ids = set(_sorted_string_list(after.get("bundle_ids")))
    before_uuids = set(_sorted_string_list(before.get("application_uuids")))
    after_uuids = set(_sorted_string_list(after.get("application_uuids")))
    before_unknown = set(_sorted_string_list(before.get("unknown_items")))
    after_unknown = set(_sorted_string_list(after.get("unknown_items")))
    before_refs_value = before.get("references")
    after_refs_value = after.get("references")
    before_refs = before_refs_value if isinstance(before_refs_value, dict) else {}
    after_refs = after_refs_value if isinstance(after_refs_value, dict) else {}
    reference_keys = set(before_refs.keys()) | set(after_refs.keys())
    return {
        "added_artifacts": sorted(after_artifacts - before_artifacts),
        "removed_artifacts": sorted(before_artifacts - after_artifacts),
        "added_bundle_ids": sorted(after_bundle_ids - before_bundle_ids),
        "removed_bundle_ids": sorted(before_bundle_ids - after_bundle_ids),
        "added_application_uuids": sorted(after_uuids - before_uuids),
        "removed_application_uuids": sorted(before_uuids - after_uuids),
        "changed_references": sorted(key for key in reference_keys if before_refs.get(key) != after_refs.get(key)),
        "resolved_unknown_items": sorted(before_unknown - after_unknown),
        "new_unknown_items": sorted(after_unknown - before_unknown),
    }


def _bundle_networkextension_correlation_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_correlation_summary")
    after_value = after_report.get("networkextension_correlation_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("generation_ids")))
    after_ids = set(_sorted_string_list(after.get("generation_ids")))
    before_confirmed = set(_sorted_string_list(before.get("confirmed_generation_ids")))
    after_confirmed = set(_sorted_string_list(after.get("confirmed_generation_ids")))
    before_conflicting = set(_sorted_string_list(before.get("conflicting_generation_ids")))
    after_conflicting = set(_sorted_string_list(after.get("conflicting_generation_ids")))
    before_unknown = set(_sorted_string_list(before.get("unknown_generation_ids")))
    after_unknown = set(_sorted_string_list(after.get("unknown_generation_ids")))
    return {
        "newly_confirmed_generations": sorted(after_confirmed - before_confirmed),
        "new_conflicting_generations": sorted(after_conflicting - before_conflicting),
        "resolved_unknown_generations": sorted(before_unknown - after_unknown),
        "added_generations": sorted(after_ids - before_ids),
        "removed_generations": sorted(before_ids - after_ids),
    }


def _bundle_networkextension_raw_references_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_raw_references_summary")
    after_value = after_report.get("networkextension_raw_references_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    keys = [
        "total_raw_references",
        "artifacts_with_chrome_references",
        "candidate_local_network_store_references",
        "broad_cache_or_blob_references",
        "structurally_bound_references",
        "non_actionable_references",
    ]
    return {f"{key}_delta": int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}


def _bundle_networkextension_object_graph_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_object_graph_summary")
    after_value = after_report.get("networkextension_object_graph_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_indices = set(_sorted_string_list(before.get("referenced_object_indices")))
    after_indices = set(_sorted_string_list(after.get("referenced_object_indices")))
    before_bindings = before.get("binding_classifications") if isinstance(before.get("binding_classifications"), dict) else {}
    after_bindings = after.get("binding_classifications") if isinstance(after.get("binding_classifications"), dict) else {}
    before_safety = before.get("safety_classifications") if isinstance(before.get("safety_classifications"), dict) else {}
    after_safety = after.get("safety_classifications") if isinstance(after.get("safety_classifications"), dict) else {}
    before_chains = set(_sorted_string_list(before.get("parent_chain_summaries")))
    after_chains = set(_sorted_string_list(after.get("parent_chain_summaries")))
    return {
        "added_decoded_artifacts": max(0, int(after.get("decoded_artifacts", 0)) - int(before.get("decoded_artifacts", 0))),
        "removed_decoded_artifacts": max(0, int(before.get("decoded_artifacts", 0)) - int(after.get("decoded_artifacts", 0))),
        "added_referenced_object_indices": sorted(after_indices - before_indices),
        "removed_referenced_object_indices": sorted(before_indices - after_indices),
        "changed_binding_classifications": sorted(set(before_bindings) ^ set(after_bindings) | {key for key in set(before_bindings) & set(after_bindings) if before_bindings.get(key) != after_bindings.get(key)}),
        "changed_safety_classifications": sorted(set(before_safety) ^ set(after_safety) | {key for key in set(before_safety) & set(after_safety) if before_safety.get(key) != after_safety.get(key)}),
        "changed_parent_chain_summaries": sorted(before_chains ^ after_chains),
    }


def _bundle_networkextension_repair_candidate_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_repair_candidates_summary")
    after_value = after_report.get("networkextension_repair_candidates_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_refs = set(_sorted_string_list(before.get("candidate_object_refs")))
    after_refs = set(_sorted_string_list(after.get("candidate_object_refs")))
    before_safety = before.get("safety_classifications") if isinstance(before.get("safety_classifications"), dict) else {}
    after_safety = after.get("safety_classifications") if isinstance(after.get("safety_classifications"), dict) else {}
    return {
        "added_candidate_object_refs": sorted(after_refs - before_refs),
        "removed_candidate_object_refs": sorted(before_refs - after_refs),
        "changed_safety_classifications": sorted(set(before_safety) ^ set(after_safety) | {key for key in set(before_safety) & set(after_safety) if before_safety.get(key) != after_safety.get(key)}),
        "duplicate_records_delta": int(after.get("duplicate_records", 0)) - int(before.get("duplicate_records", 0)),
        "orphaned_records_delta": int(after.get("orphaned_records", 0)) - int(before.get("orphaned_records", 0)),
        "code_sign_clone_only_records_delta": int(after.get("code_sign_clone_only_records", 0)) - int(before.get("code_sign_clone_only_records", 0)),
    }


def _bundle_networkextension_candidate_validation_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_candidate_validation_summary")
    after_value = after_report.get("networkextension_candidate_validation_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_refs = set(_sorted_string_list(before.get("candidate_refs")))
    after_refs = set(_sorted_string_list(after.get("candidate_refs")))
    before_status = before.get("status_counts") if isinstance(before.get("status_counts"), dict) else {}
    after_status = after.get("status_counts") if isinstance(after.get("status_counts"), dict) else {}
    return {
        "added_candidate_refs": sorted(after_refs - before_refs),
        "removed_candidate_refs": sorted(before_refs - after_refs),
        "changed_statuses": sorted(set(before_status) ^ set(after_status) | {key for key in set(before_status) & set(after_status) if before_status.get(key) != after_status.get(key)}),
        "runtime_absent_records_delta": int(after.get("runtime_absent_records", 0)) - int(before.get("runtime_absent_records", 0)),
        "stale_records_delta": int(after.get("stale_records", 0)) - int(before.get("stale_records", 0)),
        "unverifiable_records_delta": int(after.get("unverifiable_records", 0)) - int(before.get("unverifiable_records", 0)),
    }


def _bundle_networkextension_repair_plan_preview_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_repair_plan_preview_summary")
    after_value = after_report.get("networkextension_repair_plan_preview_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("preview_group_ids")))
    after_ids = set(_sorted_string_list(after.get("preview_group_ids")))
    before_classifications = before.get("classification_counts") if isinstance(before.get("classification_counts"), dict) else {}
    after_classifications = after.get("classification_counts") if isinstance(after.get("classification_counts"), dict) else {}
    return {
        "added_preview_group_ids": sorted(after_ids - before_ids),
        "removed_preview_group_ids": sorted(before_ids - after_ids),
        "changed_classifications": sorted(set(before_classifications) ^ set(after_classifications) | {key for key in set(before_classifications) & set(after_classifications) if before_classifications.get(key) != after_classifications.get(key)}),
        "grouped_preview_targets_delta": int(after.get("grouped_preview_targets", 0)) - int(before.get("grouped_preview_targets", 0)),
        "preview_only_operations_delta": int(after.get("preview_only_operations", 0)) - int(before.get("preview_only_operations", 0)),
        "stale_code_sign_clone_targets_delta": int(after.get("stale_code_sign_clone_targets", 0)) - int(before.get("stale_code_sign_clone_targets", 0)),
        "stale_missing_executable_targets_delta": int(after.get("stale_missing_executable_targets", 0)) - int(before.get("stale_missing_executable_targets", 0)),
    }


def _bundle_networkextension_repair_transaction_package_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_repair_transaction_package_summary")
    after_value = after_report.get("networkextension_repair_transaction_package_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("transaction_ids")))
    after_ids = set(_sorted_string_list(after.get("transaction_ids")))
    before_status = before.get("validation_status_counts") if isinstance(before.get("validation_status_counts"), dict) else {}
    after_status = after.get("validation_status_counts") if isinstance(after.get("validation_status_counts"), dict) else {}
    return {
        "added_transaction_ids": sorted(after_ids - before_ids),
        "removed_transaction_ids": sorted(before_ids - after_ids),
        "changed_validation_statuses": sorted(set(before_status) ^ set(after_status) | {key for key in set(before_status) & set(after_status) if before_status.get(key) != after_status.get(key)}),
        "transaction_count_delta": int(after.get("transaction_count", 0)) - int(before.get("transaction_count", 0)),
        "preview_only_transactions_delta": int(after.get("preview_only_transactions", 0)) - int(before.get("preview_only_transactions", 0)),
        "backup_required_count_delta": int(after.get("backup_required_count", 0)) - int(before.get("backup_required_count", 0)),
        "rollback_required_count_delta": int(after.get("rollback_required_count", 0)) - int(before.get("rollback_required_count", 0)),
    }


def _bundle_networkextension_manual_repair_runbook_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_manual_repair_runbook_summary")
    after_value = after_report.get("networkextension_manual_repair_runbook_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("runbook_ids")))
    after_ids = set(_sorted_string_list(after.get("runbook_ids")))
    before_difficulty = before.get("difficulty_counts") if isinstance(before.get("difficulty_counts"), dict) else {}
    after_difficulty = after.get("difficulty_counts") if isinstance(after.get("difficulty_counts"), dict) else {}
    return {
        "added_runbook_ids": sorted(after_ids - before_ids),
        "removed_runbook_ids": sorted(before_ids - after_ids),
        "changed_difficulties": sorted(set(before_difficulty) ^ set(after_difficulty) | {key for key in set(before_difficulty) & set(after_difficulty) if before_difficulty.get(key) != after_difficulty.get(key)}),
        "transaction_count_delta": int(after.get("transaction_count", 0)) - int(before.get("transaction_count", 0)),
        "requires_archive_regeneration_count_delta": int(after.get("requires_archive_regeneration_count", 0)) - int(before.get("requires_archive_regeneration_count", 0)),
        "manual_only_before": bool(before.get("manual_only", False)),
        "manual_only_after": bool(after.get("manual_only", False)),
    }


def _bundle_networkextension_repair_simulation_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_repair_simulation_summary")
    after_value = after_report.get("networkextension_repair_simulation_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("repair_simulation_ids")))
    after_ids = set(_sorted_string_list(after.get("repair_simulation_ids")))
    return {
        "added_simulation_ids": sorted(after_ids - before_ids),
        "removed_simulation_ids": sorted(before_ids - after_ids),
        "input_transactions_delta": int(after.get("input_transactions", 0)) - int(before.get("input_transactions", 0)),
        "simulated_transactions_delta": int(after.get("simulated_transactions", 0)) - int(before.get("simulated_transactions", 0)),
        "removed_object_count_delta": int(after.get("removed_object_count", 0)) - int(before.get("removed_object_count", 0)),
        "uid_rewrite_count_delta": int(after.get("uid_rewrite_count", 0)) - int(before.get("uid_rewrite_count", 0)),
        "array_changes_delta": int(after.get("array_changes", 0)) - int(before.get("array_changes", 0)),
        "dictionary_changes_delta": int(after.get("dictionary_changes", 0)) - int(before.get("dictionary_changes", 0)),
        "safety_verdict_before": str(before.get("safety_verdict", "simulation_inconclusive")),
        "safety_verdict_after": str(after.get("safety_verdict", "simulation_inconclusive")),
    }


def _bundle_networkextension_repair_artifact_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_repair_artifact_summary")
    after_value = after_report.get("networkextension_repair_artifact_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = set(_sorted_string_list(before.get("repair_artifact_ids")))
    after_ids = set(_sorted_string_list(after.get("repair_artifact_ids")))
    return {
        "added_artifact_ids": sorted(after_ids - before_ids),
        "removed_artifact_ids": sorted(before_ids - after_ids),
        "validation_result_before": str(before.get("validation_result", "not_generated")),
        "validation_result_after": str(after.get("validation_result", "not_generated")),
        "removed_object_count_delta": int(after.get("removed_object_count", 0)) - int(before.get("removed_object_count", 0)),
        "uid_rewrite_count_delta": int(after.get("uid_rewrite_count", 0)) - int(before.get("uid_rewrite_count", 0)),
        "array_change_count_delta": int(after.get("array_change_count", 0)) - int(before.get("array_change_count", 0)),
        "dictionary_change_count_delta": int(after.get("dictionary_change_count", 0)) - int(before.get("dictionary_change_count", 0)),
        "generated_artifact_sha256_before": str(before.get("generated_artifact_sha256", "")),
        "generated_artifact_sha256_after": str(after.get("generated_artifact_sha256", "")),
    }


def _json_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _bundle_networkextension_repair_apply_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_repair_apply_summary")
    after_value = after_report.get("networkextension_repair_apply_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_blockers = set(_json_string_list(before.get("blockers", [])))
    after_blockers = set(_json_string_list(after.get("blockers", [])))
    before_details_value = before.get("blocker_details")
    after_details_value = after.get("blocker_details")
    before_details = before_details_value if isinstance(before_details_value, dict) else {}
    after_details = after_details_value if isinstance(after_details_value, dict) else {}
    return {
        "status_before": str(before.get("final_status", "DRY_RUN")),
        "status_after": str(after.get("final_status", "DRY_RUN")),
        "mutation_performed_before": bool(before.get("mutation_performed", False)),
        "mutation_performed_after": bool(after.get("mutation_performed", False)),
        "backup_created_before": bool(before.get("backup_created", False)),
        "backup_created_after": bool(after.get("backup_created", False)),
        "target_path_before": str(before.get("target_path", "")),
        "target_path_after": str(after.get("target_path", "")),
        "metadata_status_before": str(before.get("metadata_status", "UNKNOWN")),
        "metadata_status_after": str(after.get("metadata_status", "UNKNOWN")),
        "preflight_status_before": str(before.get("preflight_status", "BLOCKED")),
        "preflight_status_after": str(after.get("preflight_status", "BLOCKED")),
        "added_blockers": sorted(after_blockers - before_blockers),
        "removed_blockers": sorted(before_blockers - after_blockers),
        "changed_blocker_details": sorted(code for code in before_blockers & after_blockers if before_details.get(code) != after_details.get(code)),
        "sha_mismatch_details_before": before_details.get("source_sha256_mismatch", {}),
        "sha_mismatch_details_after": after_details.get("source_sha256_mismatch", {}),
        "expected_source_sha256_before": str(before.get("expected_source_sha256", "")),
        "expected_source_sha256_after": str(after.get("expected_source_sha256", "")),
        "actual_source_sha256_before": str(before.get("actual_source_sha256", "")),
        "actual_source_sha256_after": str(after.get("actual_source_sha256", "")),
    }


def _bundle_networkextension_apply_validation_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("networkextension_apply_validation_summary")
    after_value = after_report.get("networkextension_apply_validation_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    return {
        "verdict_before": str(before.get("overall_verdict", "VALIDATION_INCONCLUSIVE")),
        "verdict_after": str(after.get("overall_verdict", "VALIDATION_INCONCLUSIVE")),
        "repair_candidates_remaining_delta": int(after.get("repair_candidates_remaining", 0)) - int(before.get("repair_candidates_remaining", 0)),
        "validation_candidates_remaining_delta": int(after.get("validation_candidates_remaining", 0)) - int(before.get("validation_candidates_remaining", 0)),
        "target_sha256_before": str(before.get("target_sha256", "")),
        "target_sha256_after": str(after.get("target_sha256", "")),
        "artifact_sha256_before": str(before.get("artifact_sha256", "")),
        "artifact_sha256_after": str(after.get("artifact_sha256", "")),
        "graph_consistency_before": str(before.get("graph_consistency", "UNKNOWN")),
        "graph_consistency_after": str(after.get("graph_consistency", "UNKNOWN")),
        "sha256_identical_before": bool(before.get("sha256_identical", False)),
        "sha256_identical_after": bool(after.get("sha256_identical", False)),
        "bytewise_sha256_identical_before": bool(before.get("bytewise_sha256_identical", before.get("sha256_identical", False))),
        "bytewise_sha256_identical_after": bool(after.get("bytewise_sha256_identical", after.get("sha256_identical", False))),
        "semantic_equivalence_before": bool(before.get("semantic_equivalence", False)),
        "semantic_equivalence_after": bool(after.get("semantic_equivalence", False)),
        "serialization_difference_explained_before": str(before.get("serialization_difference_explained", "")),
        "serialization_difference_explained_after": str(after.get("serialization_difference_explained", "")),
        "object_graph_identical_before": bool(before.get("object_graph_identical", False)),
        "object_graph_identical_after": bool(after.get("object_graph_identical", False)),
    }


def _bundle_trace_correlation_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("trace_correlation_summary")
    after_value = after_report.get("trace_correlation_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ids = _correlation_ids(before)
    after_ids = _correlation_ids(after)
    before_strength = _correlation_strength(before)
    after_strength = _correlation_strength(after)
    common = set(before_strength) & set(after_strength)
    return {
        "added_correlations": sorted(set(after_ids) - set(before_ids)),
        "removed_correlations": sorted(set(before_ids) - set(after_ids)),
        "changed_strength": sorted(key for key in common if before_strength.get(key) != after_strength.get(key)),
    }


def _correlation_ids(summary: dict[str, Any]) -> list[str]:
    result = []
    for item in summary.get("correlated", []):
        if isinstance(item, dict):
            producer = str(item.get("producer_process", ""))
            consumer = str(item.get("consumer_process", ""))
            if producer or consumer:
                result.append(f"{producer}->{consumer}")
    return sorted(result)


def _correlation_strength(summary: dict[str, Any]) -> dict[str, str]:
    result = {}
    for item in summary.get("correlated", []):
        if isinstance(item, dict):
            producer = str(item.get("producer_process", ""))
            consumer = str(item.get("consumer_process", ""))
            key = f"{producer}->{consumer}"
            result[key] = str(item.get("correlation_strength", ""))
    return result


def _bundle_trace_timeline_diff(before_report: dict[str, Any], after_report: dict[str, Any]) -> dict[str, object]:
    before_value = before_report.get("trace_timeline_summary")
    after_value = after_report.get("trace_timeline_summary")
    before = before_value if isinstance(before_value, dict) else {}
    after = after_value if isinstance(after_value, dict) else {}
    before_ops = before.get("operations") if isinstance(before.get("operations"), dict) else {}
    after_ops = after.get("operations") if isinstance(after.get("operations"), dict) else {}
    before_processes = before.get("processes") if isinstance(before.get("processes"), dict) else {}
    after_processes = after.get("processes") if isinstance(after.get("processes"), dict) else {}
    return {
        "added_events": max(0, int(after.get("event_count", 0)) - int(before.get("event_count", 0))),
        "removed_events": max(0, int(before.get("event_count", 0)) - int(after.get("event_count", 0))),
        "added_operations": sorted(set(after_ops) - set(before_ops)),
        "removed_operations": sorted(set(before_ops) - set(after_ops)),
        "added_processes": sorted(set(after_processes) - set(before_processes)),
        "removed_processes": sorted(set(before_processes) - set(after_processes)),
    }


def _sorted_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(item for item in value if isinstance(item, str))


def _render_bundle_diff(diff: dict[str, Any]) -> str:
    evidence = diff["evidence_diff"]
    files = diff["files"]
    generation = diff.get("generation_diff", {})
    outcome = diff.get("outcome_diff", {})
    provenance = diff.get("provenance_diff", {})
    producer_evidence = diff.get("producer_evidence_diff", {})
    regeneration = diff.get("regeneration_diff", {})
    cleanup_checklist = diff.get("cleanup_checklist_diff", {})
    cleanup_verification = diff.get("cleanup_verification_diff", {})
    networkextension_state = diff.get("networkextension_state_diff", {})
    networkextension_correlation = diff.get("networkextension_correlation_diff", {})
    networkextension_raw_references = diff.get("networkextension_raw_references_diff", {})
    networkextension_object_graph = diff.get("networkextension_object_graph_diff", {})
    networkextension_repair_candidates = diff.get("networkextension_repair_candidate_diff", {})
    networkextension_candidate_validation = diff.get("networkextension_candidate_validation_diff", {})
    networkextension_repair_plan_preview = diff.get("networkextension_repair_plan_preview_diff", {})
    networkextension_repair_transaction_package = diff.get("networkextension_repair_transaction_package_diff", {})
    networkextension_manual_repair_runbook = diff.get("networkextension_manual_repair_runbook_diff", {})
    networkextension_repair_simulation = diff.get("networkextension_repair_simulation_diff", {})
    networkextension_repair_artifact = diff.get("networkextension_repair_artifact_diff", {})
    networkextension_repair_apply = diff.get("networkextension_repair_apply_diff", {})
    networkextension_apply_validation = diff.get("networkextension_apply_validation_diff", {})
    trace_correlation = diff.get("trace_correlation_diff", {})
    trace_timeline = diff.get("trace_timeline_diff", {})
    lines = [
        "Support bundle diff",
        f"Before: {diff['before']['path']}",
        f"After: {diff['after']['path']}",
        "",
        "Evidence",
        f"- Added evidence: {', '.join(evidence['added']) if evidence['added'] else 'none'}",
        f"- Removed evidence: {', '.join(evidence['removed']) if evidence['removed'] else 'none'}",
        f"- Changed evidence presence: {', '.join(evidence['changed_presence']) if evidence['changed_presence'] else 'none'}",
        "",
        "Generation diff",
        f"- Removed generations: {', '.join(generation.get('removed', [])) if generation.get('removed') else 'none'}",
        f"- Added generations: {', '.join(generation.get('added', [])) if generation.get('added') else 'none'}",
        f"- Persisted generations: {', '.join(generation.get('persisted', [])) if generation.get('persisted') else 'none'}",
        f"- Regenerated generations: {', '.join(generation.get('regenerated', [])) if generation.get('regenerated') else 'none'}",
        "",
        "Outcome Diff",
        f"- Completed: {outcome.get('completed', 0)}",
        f"- Remaining: {outcome.get('remaining', 0)}",
        f"- Newly blocked: {outcome.get('newly_blocked', 0)}",
        f"- Resolved: {outcome.get('resolved', 0)}",
        f"- Status: {outcome.get('status_before', 'UNKNOWN')} → {outcome.get('status_after', 'UNKNOWN')}",
        "",
        "Provenance Diff",
        f"- Producer: {provenance.get('producer_before', 'Unknown')} → {provenance.get('producer_after', 'Unknown')}",
        f"- Persistence: {provenance.get('persistence_before', 'unknown')} → {provenance.get('persistence_after', 'unknown')}",
        f"- Added consumers: {', '.join(provenance.get('added_consumers', [])) if provenance.get('added_consumers') else 'none'}",
        f"- Removed consumers: {', '.join(provenance.get('removed_consumers', [])) if provenance.get('removed_consumers') else 'none'}",
        "",
        "Producer Evidence Diff",
        f"- Added evidence: {', '.join(producer_evidence.get('added_evidence', [])) if producer_evidence.get('added_evidence') else 'none'}",
        f"- Removed evidence: {', '.join(producer_evidence.get('removed_evidence', [])) if producer_evidence.get('removed_evidence') else 'none'}",
        f"- Changed confidence: {', '.join(producer_evidence.get('changed_confidence', [])) if producer_evidence.get('changed_confidence') else 'none'}",
        f"- Changed observed status: {', '.join(producer_evidence.get('changed_observed_status', [])) if producer_evidence.get('changed_observed_status') else 'none'}",
        "",
        "Regeneration Diff",
        f"- Regenerator: {regeneration.get('regenerator_before', 'Unknown')} → {regeneration.get('regenerator_after', 'Unknown')}",
        f"- High confidence delta: {regeneration.get('high_confidence_delta', 0)}",
        f"- Unknown delta: {regeneration.get('unknown_delta', 0)}",
        "",
        "Cleanup Checklist Diff",
        f"- Added items: {', '.join(cleanup_checklist.get('added_item_ids', [])) if cleanup_checklist.get('added_item_ids') else 'none'}",
        f"- Removed items: {', '.join(cleanup_checklist.get('removed_item_ids', [])) if cleanup_checklist.get('removed_item_ids') else 'none'}",
        f"- Changed items: {', '.join(cleanup_checklist.get('changed_item_ids', [])) if cleanup_checklist.get('changed_item_ids') else 'none'}",
        f"- First recommended action changed: {cleanup_checklist.get('first_recommended_action_changed', False)}",
        "",
        "Cleanup Verification Diff",
        f"- Verified items: {', '.join(cleanup_verification.get('verified_items', [])) if cleanup_verification.get('verified_items') else 'none'}",
        f"- Failed verification: {', '.join(cleanup_verification.get('failed_verification', [])) if cleanup_verification.get('failed_verification') else 'none'}",
        f"- Newly appeared generations: {', '.join(cleanup_verification.get('newly_appeared_generations', [])) if cleanup_verification.get('newly_appeared_generations') else 'none'}",
        f"- Disappeared generations: {', '.join(cleanup_verification.get('disappeared_generations', [])) if cleanup_verification.get('disappeared_generations') else 'none'}",
        f"- Unchanged generations: {', '.join(cleanup_verification.get('unchanged_generations', [])) if cleanup_verification.get('unchanged_generations') else 'none'}",
        "",
        "NetworkExtension State Diff",
        f"- Added artifacts: {', '.join(networkextension_state.get('added_artifacts', [])) if networkextension_state.get('added_artifacts') else 'none'}",
        f"- Removed artifacts: {', '.join(networkextension_state.get('removed_artifacts', [])) if networkextension_state.get('removed_artifacts') else 'none'}",
        f"- Added bundle IDs: {', '.join(networkextension_state.get('added_bundle_ids', [])) if networkextension_state.get('added_bundle_ids') else 'none'}",
        f"- Removed bundle IDs: {', '.join(networkextension_state.get('removed_bundle_ids', [])) if networkextension_state.get('removed_bundle_ids') else 'none'}",
        f"- Added application UUIDs: {', '.join(networkextension_state.get('added_application_uuids', [])) if networkextension_state.get('added_application_uuids') else 'none'}",
        f"- Removed application UUIDs: {', '.join(networkextension_state.get('removed_application_uuids', [])) if networkextension_state.get('removed_application_uuids') else 'none'}",
        f"- Changed references: {', '.join(networkextension_state.get('changed_references', [])) if networkextension_state.get('changed_references') else 'none'}",
        f"- Resolved unknowns: {', '.join(networkextension_state.get('resolved_unknown_items', [])) if networkextension_state.get('resolved_unknown_items') else 'none'}",
        f"- New unknowns: {', '.join(networkextension_state.get('new_unknown_items', [])) if networkextension_state.get('new_unknown_items') else 'none'}",
        "",
        "NetworkExtension Correlation Diff",
        f"- Newly confirmed generations: {', '.join(networkextension_correlation.get('newly_confirmed_generations', [])) if networkextension_correlation.get('newly_confirmed_generations') else 'none'}",
        f"- New conflicting generations: {', '.join(networkextension_correlation.get('new_conflicting_generations', [])) if networkextension_correlation.get('new_conflicting_generations') else 'none'}",
        f"- Resolved unknown generations: {', '.join(networkextension_correlation.get('resolved_unknown_generations', [])) if networkextension_correlation.get('resolved_unknown_generations') else 'none'}",
        f"- Added generations: {', '.join(networkextension_correlation.get('added_generations', [])) if networkextension_correlation.get('added_generations') else 'none'}",
        f"- Removed generations: {', '.join(networkextension_correlation.get('removed_generations', [])) if networkextension_correlation.get('removed_generations') else 'none'}",
        "",
        "NetworkExtension Raw References Diff",
        f"- Total raw references: {networkextension_raw_references.get('total_raw_references_delta', 0):+d}",
        f"- Artifacts with Chrome references: {networkextension_raw_references.get('artifacts_with_chrome_references_delta', 0):+d}",
        f"- Candidate Local Network store references: {networkextension_raw_references.get('candidate_local_network_store_references_delta', 0):+d}",
        f"- Broad cache/blob references: {networkextension_raw_references.get('broad_cache_or_blob_references_delta', 0):+d}",
        f"- Structurally bound references: {networkextension_raw_references.get('structurally_bound_references_delta', 0):+d}",
        f"- Non-actionable references: {networkextension_raw_references.get('non_actionable_references_delta', 0):+d}",
        "",
        "NetworkExtension Object Graph Diff",
        f"- Added decoded artifacts: {networkextension_object_graph.get('added_decoded_artifacts', 0)}",
        f"- Removed decoded artifacts: {networkextension_object_graph.get('removed_decoded_artifacts', 0)}",
        f"- Added referenced object indices: {', '.join(networkextension_object_graph.get('added_referenced_object_indices', [])) if networkextension_object_graph.get('added_referenced_object_indices') else 'none'}",
        f"- Removed referenced object indices: {', '.join(networkextension_object_graph.get('removed_referenced_object_indices', [])) if networkextension_object_graph.get('removed_referenced_object_indices') else 'none'}",
        f"- Changed binding classifications: {', '.join(networkextension_object_graph.get('changed_binding_classifications', [])) if networkextension_object_graph.get('changed_binding_classifications') else 'none'}",
        f"- Changed safety classifications: {', '.join(networkextension_object_graph.get('changed_safety_classifications', [])) if networkextension_object_graph.get('changed_safety_classifications') else 'none'}",
        f"- Changed parent-chain summaries: {', '.join(networkextension_object_graph.get('changed_parent_chain_summaries', [])) if networkextension_object_graph.get('changed_parent_chain_summaries') else 'none'}",
        "",
        "NetworkExtension Repair Candidate Diff",
        f"- Added candidate object refs: {', '.join(networkextension_repair_candidates.get('added_candidate_object_refs', [])) if networkextension_repair_candidates.get('added_candidate_object_refs') else 'none'}",
        f"- Removed candidate object refs: {', '.join(networkextension_repair_candidates.get('removed_candidate_object_refs', [])) if networkextension_repair_candidates.get('removed_candidate_object_refs') else 'none'}",
        f"- Changed safety classifications: {', '.join(networkextension_repair_candidates.get('changed_safety_classifications', [])) if networkextension_repair_candidates.get('changed_safety_classifications') else 'none'}",
        f"- Duplicate records: {networkextension_repair_candidates.get('duplicate_records_delta', 0):+d}",
        f"- Orphaned records: {networkextension_repair_candidates.get('orphaned_records_delta', 0):+d}",
        f"- Code-sign-clone-only records: {networkextension_repair_candidates.get('code_sign_clone_only_records_delta', 0):+d}",
        "",
        "NetworkExtension Candidate Validation Diff",
        f"- Added candidate refs: {', '.join(networkextension_candidate_validation.get('added_candidate_refs', [])) if networkextension_candidate_validation.get('added_candidate_refs') else 'none'}",
        f"- Removed candidate refs: {', '.join(networkextension_candidate_validation.get('removed_candidate_refs', [])) if networkextension_candidate_validation.get('removed_candidate_refs') else 'none'}",
        f"- Changed statuses: {', '.join(networkextension_candidate_validation.get('changed_statuses', [])) if networkextension_candidate_validation.get('changed_statuses') else 'none'}",
        f"- Runtime absent records: {networkextension_candidate_validation.get('runtime_absent_records_delta', 0):+d}",
        f"- Stale records: {networkextension_candidate_validation.get('stale_records_delta', 0):+d}",
        f"- Unverifiable records: {networkextension_candidate_validation.get('unverifiable_records_delta', 0):+d}",
        "",
        "NetworkExtension Repair Plan Preview Diff",
        f"- Added preview groups: {', '.join(networkextension_repair_plan_preview.get('added_preview_group_ids', [])) if networkextension_repair_plan_preview.get('added_preview_group_ids') else 'none'}",
        f"- Removed preview groups: {', '.join(networkextension_repair_plan_preview.get('removed_preview_group_ids', [])) if networkextension_repair_plan_preview.get('removed_preview_group_ids') else 'none'}",
        f"- Changed classifications: {', '.join(networkextension_repair_plan_preview.get('changed_classifications', [])) if networkextension_repair_plan_preview.get('changed_classifications') else 'none'}",
        f"- Grouped preview targets: {networkextension_repair_plan_preview.get('grouped_preview_targets_delta', 0):+d}",
        f"- Preview-only operations: {networkextension_repair_plan_preview.get('preview_only_operations_delta', 0):+d}",
        f"- Stale code_sign_clone targets: {networkextension_repair_plan_preview.get('stale_code_sign_clone_targets_delta', 0):+d}",
        f"- Stale missing executable targets: {networkextension_repair_plan_preview.get('stale_missing_executable_targets_delta', 0):+d}",
        "",
        "NetworkExtension Repair Transaction Package Diff",
        f"- Added transactions: {', '.join(networkextension_repair_transaction_package.get('added_transaction_ids', [])) if networkextension_repair_transaction_package.get('added_transaction_ids') else 'none'}",
        f"- Removed transactions: {', '.join(networkextension_repair_transaction_package.get('removed_transaction_ids', [])) if networkextension_repair_transaction_package.get('removed_transaction_ids') else 'none'}",
        f"- Changed validation statuses: {', '.join(networkextension_repair_transaction_package.get('changed_validation_statuses', [])) if networkextension_repair_transaction_package.get('changed_validation_statuses') else 'none'}",
        f"- Transaction count: {networkextension_repair_transaction_package.get('transaction_count_delta', 0):+d}",
        f"- Preview-only transactions: {networkextension_repair_transaction_package.get('preview_only_transactions_delta', 0):+d}",
        f"- Backup required: {networkextension_repair_transaction_package.get('backup_required_count_delta', 0):+d}",
        f"- Rollback required: {networkextension_repair_transaction_package.get('rollback_required_count_delta', 0):+d}",
        "",
        "NetworkExtension Manual Repair Runbook Diff",
        f"- Added runbooks: {', '.join(networkextension_manual_repair_runbook.get('added_runbook_ids', [])) if networkextension_manual_repair_runbook.get('added_runbook_ids') else 'none'}",
        f"- Removed runbooks: {', '.join(networkextension_manual_repair_runbook.get('removed_runbook_ids', [])) if networkextension_manual_repair_runbook.get('removed_runbook_ids') else 'none'}",
        f"- Changed difficulties: {', '.join(networkextension_manual_repair_runbook.get('changed_difficulties', [])) if networkextension_manual_repair_runbook.get('changed_difficulties') else 'none'}",
        f"- Transaction count: {networkextension_manual_repair_runbook.get('transaction_count_delta', 0):+d}",
        f"- Requires archive regeneration: {networkextension_manual_repair_runbook.get('requires_archive_regeneration_count_delta', 0):+d}",
        "",
        "NetworkExtension Repair Simulation Diff",
        f"- Added simulations: {', '.join(networkextension_repair_simulation.get('added_simulation_ids', [])) if networkextension_repair_simulation.get('added_simulation_ids') else 'none'}",
        f"- Removed simulations: {', '.join(networkextension_repair_simulation.get('removed_simulation_ids', [])) if networkextension_repair_simulation.get('removed_simulation_ids') else 'none'}",
        f"- Safety verdict: {networkextension_repair_simulation.get('safety_verdict_before', 'simulation_inconclusive')} → {networkextension_repair_simulation.get('safety_verdict_after', 'simulation_inconclusive')}",
        f"- Input transactions: {networkextension_repair_simulation.get('input_transactions_delta', 0):+d}",
        f"- Simulated transactions: {networkextension_repair_simulation.get('simulated_transactions_delta', 0):+d}",
        f"- Removed objects: {networkextension_repair_simulation.get('removed_object_count_delta', 0):+d}",
        f"- UID rewrites: {networkextension_repair_simulation.get('uid_rewrite_count_delta', 0):+d}",
        "",
        "NetworkExtension Repair Artifact Diff",
        f"- Added artifacts: {', '.join(networkextension_repair_artifact.get('added_artifact_ids', [])) if networkextension_repair_artifact.get('added_artifact_ids') else 'none'}",
        f"- Removed artifacts: {', '.join(networkextension_repair_artifact.get('removed_artifact_ids', [])) if networkextension_repair_artifact.get('removed_artifact_ids') else 'none'}",
        f"- Validation result: {networkextension_repair_artifact.get('validation_result_before', 'not_generated')} → {networkextension_repair_artifact.get('validation_result_after', 'not_generated')}",
        f"- Removed objects: {networkextension_repair_artifact.get('removed_object_count_delta', 0):+d}",
        f"- UID rewrites: {networkextension_repair_artifact.get('uid_rewrite_count_delta', 0):+d}",
        f"- Generated SHA256: {networkextension_repair_artifact.get('generated_artifact_sha256_after', '') or 'none'}",
        "",
        "NetworkExtension Repair Apply Diff",
        f"- Status: {networkextension_repair_apply.get('status_before', 'DRY_RUN')} → {networkextension_repair_apply.get('status_after', 'DRY_RUN')}",
        f"- Mutation performed: {str(networkextension_repair_apply.get('mutation_performed_before', False)).lower()} → {str(networkextension_repair_apply.get('mutation_performed_after', False)).lower()}",
        f"- Backup created: {str(networkextension_repair_apply.get('backup_created_before', False)).lower()} → {str(networkextension_repair_apply.get('backup_created_after', False)).lower()}",
        f"- Target path: {networkextension_repair_apply.get('target_path_after', '') or 'none'}",
        f"- Added blockers: {', '.join(networkextension_repair_apply.get('added_blockers', [])) if networkextension_repair_apply.get('added_blockers') else 'none'}",
        f"- Removed blockers: {', '.join(networkextension_repair_apply.get('removed_blockers', [])) if networkextension_repair_apply.get('removed_blockers') else 'none'}",
        f"- SHA mismatch: expected {networkextension_repair_apply.get('expected_source_sha256_after', '') or 'none'}, actual {networkextension_repair_apply.get('actual_source_sha256_after', '') or 'none'}",
        "",
        "NetworkExtension Apply Validation Diff",
        f"- Validation result: {networkextension_apply_validation.get('verdict_before', 'VALIDATION_INCONCLUSIVE')} → {networkextension_apply_validation.get('verdict_after', 'VALIDATION_INCONCLUSIVE')}",
        f"- Repair candidates remaining: {networkextension_apply_validation.get('repair_candidates_remaining_delta', 0):+d}",
        f"- Validation candidates remaining: {networkextension_apply_validation.get('validation_candidates_remaining_delta', 0):+d}",
        f"- Target SHA256: {networkextension_apply_validation.get('target_sha256_before', '') or 'none'} → {networkextension_apply_validation.get('target_sha256_after', '') or 'none'}",
        f"- Artifact SHA256: {networkextension_apply_validation.get('artifact_sha256_before', '') or 'none'} → {networkextension_apply_validation.get('artifact_sha256_after', '') or 'none'}",
        f"- Semantic equivalence: {str(networkextension_apply_validation.get('semantic_equivalence_before', False)).lower()} → {str(networkextension_apply_validation.get('semantic_equivalence_after', False)).lower()}",
        f"- Byte-identical: {str(networkextension_apply_validation.get('bytewise_sha256_identical_before', False)).lower()} → {str(networkextension_apply_validation.get('bytewise_sha256_identical_after', False)).lower()}",
        f"- Serialization explanation: {networkextension_apply_validation.get('serialization_difference_explained_after', '') or 'none'}",
        f"- Graph consistency: {networkextension_apply_validation.get('graph_consistency_before', 'UNKNOWN')} → {networkextension_apply_validation.get('graph_consistency_after', 'UNKNOWN')}",
        "",
        "Trace Correlation Diff",
        f"- Added correlations: {', '.join(trace_correlation.get('added_correlations', [])) if trace_correlation.get('added_correlations') else 'none'}",
        f"- Removed correlations: {', '.join(trace_correlation.get('removed_correlations', [])) if trace_correlation.get('removed_correlations') else 'none'}",
        f"- Changed strength: {', '.join(trace_correlation.get('changed_strength', [])) if trace_correlation.get('changed_strength') else 'none'}",
        "",
        "Trace Timeline Diff",
        f"- Added events: {trace_timeline.get('added_events', 0)}",
        f"- Removed events: {trace_timeline.get('removed_events', 0)}",
        f"- Added operations: {', '.join(trace_timeline.get('added_operations', [])) if trace_timeline.get('added_operations') else 'none'}",
        f"- Added processes: {', '.join(trace_timeline.get('added_processes', [])) if trace_timeline.get('added_processes') else 'none'}",
        "",
        "Changed fields",
        f"- {', '.join(diff['changed_fields']) if diff['changed_fields'] else 'none'}",
        "",
        "Files",
        f"- Added files: {', '.join(files['added']) if files['added'] else 'none'}",
        f"- Removed files: {', '.join(files['removed']) if files['removed'] else 'none'}",
    ]
    return "\n".join(lines)


@diff_app.command("bundles")
def diff_bundles_cmd(
    before: Path,
    after: Path,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    try:
        diff = _diff_support_bundles(before, after)
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(1) from error
    if json_output:
        typer.echo(json_module.dumps(diff, sort_keys=False))
    else:
        console.print(_render_bundle_diff(diff), markup=False)


@report_app.command("local-network")
def report_local_network_cmd(
    branch: str = "manual-empty-trash-reboot",
    trace: Path | None = None,
    audit_log: list[Path] | None = typer.Option(None, "--audit-log", help="Read LaunchServices execute-plan audit JSONL for outcome history; may be repeated."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    bundle: Path | None = typer.Option(None, "--bundle", help="Write a deterministic support bundle directory."),
):
    snap = create_snapshot(fast=True)
    report = build_local_network_report(snap, trace_analysis=load_trace_analysis(trace), branch_id=branch, launchservices_audit_log=audit_log)
    if bundle is not None:
        try:
            write_local_network_support_bundle(report, bundle, branch_id=branch, trace_path=trace, launchservices_audit_log=audit_log)
        except ValueError as error:
            typer.echo(str(error))
            raise typer.Exit(1) from error
    if json_output:
        typer.echo(json_module.dumps(report.to_json_dict(), sort_keys=False))
    else:
        console.print(report.render_text(), markup=False)


@report_app.command("launchservices")
def report_launchservices_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    bundle: Path | None = typer.Option(None, "--bundle", help="Write a deterministic support bundle directory."),
):
    snap = create_snapshot(fast=True)
    report = build_launchservices_report(snap)
    if bundle is not None:
        try:
            write_launchservices_support_bundle(report, bundle)
        except ValueError as error:
            typer.echo(str(error))
            raise typer.Exit(1) from error
    if json_output:
        typer.echo(json_module.dumps(report.to_json_dict(), sort_keys=False))
    else:
        console.print(report.render_text(), markup=False)


@app.command()
def doctor():
    snap = create_snapshot(fast=True)
    evidence = extract_evidence(snap)
    plan = build_remediation_plan(evidence)

    console.print("[bold]Evidence[/bold]")
    if not evidence.items:
        console.print("  No evidence items found.")
    for item in evidence.items:
        console.print(f"  - [bold]{item.title}[/bold] ({item.severity}, {item.confidence:.0%})")
        console.print(f"    {item.summary}")

    console.print("[bold]Hypotheses[/bold]")
    for h in snap.hypotheses:
        console.print(f"[bold]{h.title}[/bold] — {h.confidence:.0%}")
        for e in h.evidence:
            console.print(f"  - {e}")

    console.print("[bold]Remediation Plan[/bold]")
    console.print(plan.summary)
    for action in plan.actions:
        console.print(f"  - [bold]{action.title}[/bold] ({action.risk}, {action.mode})")
        console.print(f"    {action.description}")
        for command in action.commands:
            console.print(f"    $ {command}")


if __name__ == "__main__":
    app()
