from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json as json_module
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
from macos_state_explorer.remediation.rules import build_remediation_plan
from macos_state_explorer.reports.html import write_report
from macos_state_explorer.reports.launchservices import build_launchservices_report, write_launchservices_support_bundle
from macos_state_explorer.reports.launchservices_html import write_launchservices_html
from macos_state_explorer.reports.local_network import build_local_network_report, write_local_network_support_bundle
from macos_state_explorer.solver.launchservices import build_launchservices_solution
from macos_state_explorer.solver.local_network import build_local_network_solution, load_trace_analysis
from macos_state_explorer.tracers.local_network import trace_json_payload, trace_local_network

app = typer.Typer(no_args_is_help=True)
trace_app = typer.Typer(no_args_is_help=True)
experiment_app = typer.Typer(no_args_is_help=True)
diagnose_app = typer.Typer(no_args_is_help=True)
solve_app = typer.Typer(no_args_is_help=True)
verify_app = typer.Typer(no_args_is_help=True)
report_app = typer.Typer(no_args_is_help=True)
repair_app = typer.Typer(no_args_is_help=True)
app.add_typer(trace_app, name="trace")
app.add_typer(experiment_app, name="experiment")
app.add_typer(diagnose_app, name="diagnose")
app.add_typer(solve_app, name="solve")
app.add_typer(verify_app, name="verify")
app.add_typer(report_app, name="report")
app.add_typer(repair_app, name="repair")
console = Console()


@app.command()
def collect(out: Path, fast: bool = False):
    snap = create_snapshot(fast=fast)
    write_report(out.expanduser(), snap)
    console.print(f"[green]Report:[/green] {out.expanduser() / 'index.html'}")


@app.command()
def launchservices(out: Path):
    out = out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    obs = LaunchServicesCollector().collect()
    write_json(out / "launchservices.json", obs)
    write_launchservices_html(out, obs.payload)
    stale = obs.payload.get("stale_entries", [])
    write_json(out / "stale-launchservices.json", stale)
    console.print(f"[green]LaunchServices output:[/green] {out}")
    console.print(f"Stale entries: {len(stale)}")


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
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    snap = create_snapshot(fast=True)
    solution = build_local_network_solution(snap, trace_analysis=load_trace_analysis(trace))
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
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
):
    snap = create_snapshot(fast=True)
    result = verify_local_network(snap, expected_branch_id=branch, trace_analysis=load_trace_analysis(trace))
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
    engine = FrameworkDiagnosticEngine(_local_network_module_with_repair_verifier())
    if action is not None or branch is not None:
        result = engine.repair(
            snap,
            action_id=action,
            candidate_id=branch,
            dry_run=dry_run,
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
        dry_run=dry_run,
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


def _verify_local_network_repair_step(snapshot, candidate, context=None) -> RepairVerification:
    context = context or {}
    trace_analysis = context.get("trace_analysis")
    verification = verify_local_network(
        snapshot,
        expected_branch_id=candidate.id,
        trace_analysis=trace_analysis if isinstance(trace_analysis, dict) else None,
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


@report_app.command("local-network")
def report_local_network_cmd(
    branch: str = "manual-empty-trash-reboot",
    trace: Path | None = None,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    bundle: Path | None = typer.Option(None, "--bundle", help="Write a deterministic support bundle directory."),
):
    snap = create_snapshot(fast=True)
    report = build_local_network_report(snap, trace_analysis=load_trace_analysis(trace), branch_id=branch)
    if bundle is not None:
        try:
            write_local_network_support_bundle(report, bundle, branch_id=branch, trace_path=trace)
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
