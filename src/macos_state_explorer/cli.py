from __future__ import annotations

from pathlib import Path
import typer
from rich.console import Console

from macos_state_explorer.collectors.launchservices import LaunchServicesCollector
from macos_state_explorer.core.snapshot import create_snapshot
from macos_state_explorer.core.util import write_json
from macos_state_explorer.evidence.engine import extract_evidence
from macos_state_explorer.experiments.local_network import experiment_local_network
from macos_state_explorer.remediation.rules import build_remediation_plan
from macos_state_explorer.reports.html import write_report
from macos_state_explorer.reports.launchservices_html import write_launchservices_html
from macos_state_explorer.tracers.local_network import trace_local_network

app = typer.Typer(no_args_is_help=True)
trace_app = typer.Typer(no_args_is_help=True)
experiment_app = typer.Typer(no_args_is_help=True)
app.add_typer(trace_app, name="trace")
app.add_typer(experiment_app, name="experiment")
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
def trace_local_network_cmd(out: Path, seconds: int | None = None):
    trace_local_network(out.expanduser(), seconds=seconds)


@experiment_app.command("local-network")
def experiment_local_network_cmd(out: Path):
    experiment_local_network(out.expanduser())


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
