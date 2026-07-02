from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stdout
from dataclasses import replace
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
from macos_state_explorer.launchservices.generations import analyze_generations, render_generation_summary
from macos_state_explorer.launchservices.remediation_plan import (
    LaunchServicesRemediationPlan,
    RemediationSafety,
    plan_launchservices_remediation,
    render_remediation_plan,
)
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


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def launchservices(
    ctx: typer.Context,
    out: Path = typer.Argument(..., help="Output directory, or 'analyze' for root-cause analysis."),
):
    if str(out) in {"analyze", "generations", "plan", "execute-plan"}:
        snap = create_snapshot(fast=True)
        payload = next((observation.payload for observation in snap.observations if observation.collector == "launchservices"), {})
        payload = payload if isinstance(payload, dict) else {}
        if str(out) in {"generations", "plan", "execute-plan"}:
            generations = analyze_generations(analysis_records_from_snapshot_payload(payload))
            if str(out) == "execute-plan":
                plan = plan_launchservices_remediation(generations)
                audit_log = _option_path(ctx.args, "--audit-log")
                if "--confirm" in ctx.args:
                    execution = _launchservices_execute_plan_confirm(plan, generations, audit_log=audit_log)
                    if "--json" in ctx.args:
                        typer.echo(json_module.dumps(execution, sort_keys=False))
                    else:
                        console.print(_render_launchservices_execute_plan_execution(execution), markup=False)
                    if execution["status"] != "SUCCESS":
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
    status = "SUCCESS"
    after_analysis = before_analysis

    for step in plan.steps:
        if not _is_phase1_executable_step(step):
            continue
        invariant_errors = _validate_step_invariants(step, current_analysis)
        if invariant_errors:
            status = "FAILED"
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
            after_snapshot = create_snapshot(fast=True)
            after_payload = next((observation.payload for observation in after_snapshot.observations if observation.collector == "launchservices"), {})
            after_payload = after_payload if isinstance(after_payload, dict) else {}
            after_analysis = analyze_generations(analysis_records_from_snapshot_payload(after_payload))
        verification_errors = list(errors)
        verification = _verification_result(
            before_analysis=current_analysis,
            after_analysis=after_analysis,
            step=step,
            command_results=command_results,
            errors=verification_errors,
        )
        step_result = _executed_step_result(step, command_results, verification, verification_errors)
        executed_steps.append(step_result)
        _write_launchservices_generation_audit(audit_log, plan.plan_id, step_result)
        if verification["result"] != "SUCCESS":
            status = "FAILED"
            errors.extend(error for error in verification["errors"] if error not in errors)
            break
        current_analysis = after_analysis

    if status == "SUCCESS":
        after_analysis = current_analysis
    return {
        "command": "launchservices execute-plan",
        "plan_id": plan.plan_id,
        "dry_run": False,
        "confirmed": True,
        "status": status,
        "product_family": plan.product_family,
        "before_generation_count": before_generation_count,
        "after_generation_count": len(after_analysis.generations),
        "active_generation_before": active_before,
        "active_generation_after": plan_launchservices_remediation(after_analysis).active_generation,
        "executed_steps": executed_steps,
        "skipped_steps": skipped_steps,
        "commands_executed": commands_executed,
        "verification_commands": list(plan.verification_commands),
        "warnings": list(plan.warnings),
        "errors": errors,
        "message": "Executed only PLAN_ONLY_SAFE LaunchServices generation steps." if status == "SUCCESS" else "Stopped immediately after an unexpected verification result.",
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
    return {"command": command, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def _verification_result(*, before_analysis, after_analysis, step, command_results: list[dict[str, object]], errors: list[str]) -> dict[str, object]:
    before_ids = {generation.generation_id for generation in before_analysis.generations}
    after_ids = {generation.generation_id for generation in after_analysis.generations}
    active_before = plan_launchservices_remediation(before_analysis).active_generation
    active_after = plan_launchservices_remediation(after_analysis).active_generation
    generation_removed = step.generation_id in before_ids and step.generation_id not in after_ids
    generation_count_decreased = len(after_ids) < len(before_ids)
    active_generation_unchanged = active_before == active_after
    local_network_status = "consistent"
    before_solution = build_local_network_solution(_snapshot_from_analysis(before_analysis))
    after_solution = build_local_network_solution(_snapshot_from_analysis(after_analysis))
    before_steps = before_solution.to_json_dict().get("remediation_plan_summary", {}).get("step_count", 0)
    after_steps = after_solution.to_json_dict().get("remediation_plan_summary", {}).get("step_count", 0)
    evidence_improves_or_consistent = int(after_steps) <= int(before_steps)
    verification_errors = list(errors)
    if not generation_count_decreased:
        verification_errors.append("Generation count did not decrease after mutation.")
    if not generation_removed:
        verification_errors.append(f"Generation {step.generation_id} still exists after mutation.")
    if not active_generation_unchanged:
        verification_errors.append("Active generation changed after mutation.")
    if not evidence_improves_or_consistent:
        verification_errors.append("Local Network evidence worsened after mutation.")
    return {
        "result": "SUCCESS" if not verification_errors and all(int(result.get("exit_code", 1)) == 0 for result in command_results) else "FAILED",
        "before_generation_count": len(before_ids),
        "after_generation_count": len(after_ids),
        "generation_count_decreased": generation_count_decreased,
        "active_generation_unchanged": active_generation_unchanged,
        "generation_removed": generation_removed,
        "local_network_evidence": local_network_status,
        "local_network_evidence_improves_or_consistent": evidence_improves_or_consistent,
        "errors": verification_errors,
    }


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
    return {
        "step_id": step.step_id,
        "generation_id": step.generation_id,
        "registration_ids": registration_ids,
        "registration_count": len(registration_ids),
        "safety": step.safety.value,
        "mutation_performed": bool(commands),
        "commands": commands,
        "verification": verification,
        "result": verification["result"],
        "errors": errors,
        "rollback_metadata": "Re-register affected application bundle manually or restore LaunchServices database from system backup if needed.",
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
        "commands": step_result["commands"],
        "verification": step_result["verification"],
        "before_generation_count": step_result["verification"]["before_generation_count"],
        "after_generation_count": step_result["verification"]["after_generation_count"],
        "errors": step_result["errors"],
        "rollback_metadata": step_result["rollback_metadata"],
    }
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
        f"Before generation count: {execution['before_generation_count']}",
        f"After generation count: {execution['after_generation_count']}",
    ]
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
    if name not in args:
        return None
    index = args.index(name)
    if index + 1 >= len(args):
        return None
    return Path(args[index + 1])


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
