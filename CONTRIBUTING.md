# Contributing

Thanks for helping improve macOS State Explorer as it evolves into **WASP Prism**.

WASP stands for **Web Application Security & Performance**. The repository remains named `macos-state-explorer` until the Chrome Local Network reference case is fully solved; the planned rename is `macos-state-explorer -> wasp-prism`.

## Project Principles

- Chrome Local Network remains priority 1.
- No new Diagnostic Engines until the Chrome reference case is fully solved.
- Keep default workflows read-only.
- Do not reset TCC.
- Do not delete caches.
- Do not unregister apps unless a narrowly scoped, confirmed, audited, documented Phase contract explicitly allows it.
- Do not change macOS system settings.
- Prefer small, testable changes.
- Preserve CLI compatibility unless a change is explicitly planned.
- Preserve JSON contracts with additive-only changes unless a breaking change is explicitly planned.

## Core vs Engine Principle

- Core must not contain domain-specific logic.
- Every domain-specific implementation must be an Engine.
- Shared project code belongs in core only when it is domain-neutral.
- LaunchServices and Chrome Local Network behavior are reference-engine logic, not core policy.
- Public engines must use the same core-vs-engine boundary.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

## Checks

Run these before opening a pull request:

```bash
ruff check .
pytest
```

## Code Guidelines

- Put macOS data collection in `src/macos_state_explorer/collectors/`.
- Put subsystem parsing and analysis in dedicated engine packages, such as `launchservices/`.
- Use typed models at module boundaries.
- Keep collectors focused on command execution and serialization.
- Add focused tests for parser, classifier, grouping, report, CLI, bundle, and JSON behavior.
- Keep audit/history as analysis input unless the milestone explicitly authorizes mutation.

## Pull Requests

Pull requests should include:

- A short summary of the change.
- Tests for changed behavior.
- Notes about any macOS commands used.
- Confirmation that no unauthorized OS-modifying operations were added.
- Documentation updates for behavior, architecture, safety, or project-identity changes.

Every architecture-affecting PR must update docs. Documentation updates are part of the Definition of Done for architecture PRs.

## Evidence-driven diagnostic lifecycle

The Chrome Local Network reference case advances through diagnosis, trace collection, planning, selective execution, persistent validation, outcome analysis, registration provenance analysis, producer evidence, trace correlation, high-fidelity timelines, and regeneration analysis. The Regeneration Analysis Engine is pure analysis: it categorizes each claim as Observed, Correlated, Inferred, or Unknown and identifies possible regeneration sources without mutation, repair, planner, solver, or diagnosis changes.
