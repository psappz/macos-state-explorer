# Architecture

macOS State Explorer is the current repository name for the public reference implementation that is evolving into **WASP Prism**.

WASP stands for **Web Application Security & Performance**. WASP Prism is the future public project identity for this evidence-driven diagnostic project. The repository rename is deferred until after the Chrome Local Network reference case is solved.

The repository stays named `macos-state-explorer` until the Chrome Local Network reference case is solved. Planned rename: `macos-state-explorer -> wasp-prism`.

## Architecture direction

WASP Prism separates reusable diagnostic platform capability from domain-specific engines.

### Core vs Engine Principle

- Core must not contain domain-specific logic.
- Every domain-specific implementation must be an Engine.
- Core owns domain-neutral snapshot, evidence, reporting, bundle, diff, audit-ingestion, CLI plumbing, and support-bundle primitives.
- Engines own domain-specific collectors, parsers, classifiers, planners, outcome models, provenance models, producer-evidence acquisition, trace-correlation evidence, remediation constraints, and user-facing interpretation.
- Architecture-affecting PRs must update documentation.

## Layers

1. Collectors
   Read system state without modifying it unless a confirmed, audited engine contract explicitly allows mutation.

2. Snapshot Store
   Stores observations in a stable versioned format.

3. Evidence and Inference
   Produces hypotheses from evidence without embedding domain rules in core. Modeled provenance must remain separate from observed producer evidence, observed consumer evidence, inferred persistence mechanism, trace correlation evidence, and unknown signals.

4. Diagnostic Engines
   Encapsulate domain-specific analysis. The macOS/LaunchServices Chrome Local Network implementation is the public reference engine and reference case.

5. Reports and Support Bundles
   Generate human-readable and machine-readable artifacts, including audit-informed outcome summaries when audit history is provided.

6. Experiments and Validation
   Run before/after workflows and persistent validation without expanding mutation scope.

## Core Concepts

- Observation
- Evidence
- Snapshot
- Hypothesis
- Diagnostic Engine
- Outcome
- Audit history
- Support bundle
- Experiment

## Current priority

Chrome Local Network remains priority 1. No new Diagnostic Engines should be added until the Chrome reference case is fully solved.

## Safety

The project defaults to read-only collection, diagnosis, and reporting. Mutation-capable workflows must be narrowly scoped, confirmed, audited, regression-tested, and documented. LaunchServices Phase 1 execution remains limited to confirmed PLAN_ONLY_SAFE obsolete Chrome generations.
