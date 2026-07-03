# Roadmap

## Project identity

Open State Diagnostics & Repair Framework is the public project name for evidence-driven diagnostics and repair.

- Repository name for now: `macos-state-explorer`.
- Repository/package/import identifiers remain unchanged for compatibility.
- The current macOS/LaunchServices work is the public reference engine and reference case.

## Version policy

- 0.x = reference-case validation.
- 1.0 = Open State Diagnostics & Repair Framework public platform baseline after Chrome reference case completion.
- 1.x = additional engines.
- 2.0 = GUI/orchestration layer.

The current package/repository remains operational under current names until a compatibility-safe rename milestone is explicitly planned. Project metadata is not renamed disruptively before the Chrome reference case is complete.

## Immediate priority

Chrome Local Network remains priority 1. No new Diagnostic Engines until the Chrome reference case is fully solved.

## v0.x Reference-case validation

- Stable Python package and Typer CLI.
- Snapshot format.
- TCC collector.
- LaunchServices collector.
- Chrome Local Network diagnosis, trace, reporting, support bundle, remediation planning, selective execution, persistent validation, and audit-informed outcome.
- Documentation updates as Definition of Done for architecture-affecting PRs.

## v1.0 Open State Diagnostics & Repair Framework public platform baseline

- Public Open State Diagnostics & Repair Framework identity after Chrome reference case completion.
- Stable core/engine boundaries.
- Stable evidence, report, support-bundle, diff, and audit-history contracts.
- Reference engine documented as the pattern for future engines.

## v1.x Additional engines

- Add new public Diagnostic Engines only after the Chrome reference case is fully solved.
- Keep Core free of domain-specific logic.
- Every domain-specific implementation must be an Engine.

## v2.0 GUI / orchestration layer

- GUI or orchestration surface above stable Open State Diagnostics & Repair Framework core and engines.
- Workflow coordination without weakening engine safety contracts.
