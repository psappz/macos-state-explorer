# Open State Diagnostics & Repair Framework v1

Open State Diagnostics & Repair Framework is the public project name for this evidence-driven diagnostic and repair framework.

## Project identity

- **Open State Diagnostics & Repair Framework** is the public project identity for this evidence-driven diagnostic project.
- This repository remains named `macos-state-explorer` for repository, package, import-path, and command-context compatibility.
- Do not rename package/import/CLI identifiers in command examples unless a compatibility-safe rename is explicitly planned.
- Documentation describes the public Open State Diagnostics & Repair Framework project while preserving technical identifiers where required.

## Current reference case

Priority 1 is the Chrome Local Network issue:

> Explain why Chrome-related apps appear in **System Settings → Privacy & Security → Local Network** even when no `kTCCServiceLocalNetwork` rows exist in `TCC.db`, then prove the safe terminal remediation/outcome state.

The current macOS/LaunchServices implementation is the public reference engine and reference case for Open State Diagnostics & Repair Framework. No new Diagnostic Engines should be added until the Chrome Local Network reference case is fully solved.

Phase 2 is investigation-driven: modeled provenance must be kept separate from observed producer evidence, observed consumer evidence, inferred persistence mechanism, trace correlation evidence, high-fidelity trace timeline evidence, regeneration evidence, and unknown signals. The Chrome Local Network reference case remains the highest priority.

The Regeneration Analysis Engine answers which observed or correlated source appears to recreate LaunchServices registrations after removal. It is evidence-only: every claim is categorized as Observed, Correlated, Inferred, or Unknown, and it performs no mutation, repair, planner, solver, or diagnosis changes.

`mse launchservices cleanup-checklist` is the manual safety bridge from analysis toward cleanup. It emits deterministic JSON/text instructions for remaining non-automatic LaunchServices sources such as Trash, mounted installers, updater-owned paths, and unknown-regenerator Chrome application generations. It is read-only and never deletes, unregisters, ejects, resets, or mutates system state.

## Install

```bash
cd macos-state-explorer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

## Commands

```bash
mse --help
mse collect ~/Desktop/mse-fast --fast-report
mse launchservices ~/Desktop/mse-ls
mse launchservices outcome
mse launchservices provenance
mse launchservices regeneration
mse launchservices cleanup-checklist
mse trace local-network ~/Desktop/mse-local-network-trace
mse report local-network --bundle ~/Desktop/mse-support-bundle
mse doctor
```

## Safety

The project defaults to read-only diagnosis and reporting. Any mutation-capable workflow must be explicitly scoped, confirmed, audited, regression-tested, and documented. LaunchServices Phase 1 mutation remains limited to confirmed PLAN_ONLY_SAFE obsolete Chrome generations only.
