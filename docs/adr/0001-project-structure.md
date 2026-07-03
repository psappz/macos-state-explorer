# 0001 Project Structure

## Context

Open State Diagnostics & Repair Framework collects read-only macOS state, stores observations, derives hypotheses, and writes reports. As the project grows, collector code can become difficult to maintain if parsing, modeling, analysis, and presentation logic live in the same modules.

## Decision

Keep the project organized by responsibility:

- `collectors/` gathers system data and returns observation payloads.
- `core/` contains shared snapshot, model, and utility code.
- `inference/` contains hypothesis logic.
- `launchservices/` contains LaunchServices-specific parsing, models, grouping, classification, and analysis.
- `reports/` contains human-readable report generation.
- `tracers/` and `experiments/` contain workflow-oriented tools.

Collectors should orchestrate command execution and serialization, but domain parsing and analysis should live in dedicated packages.

## Consequences

Domain code is easier to test without invoking macOS tools. The CLI can remain stable while internals evolve. New subsystems should follow the same separation so collector modules stay small and read-only safety remains explicit.
