# macOS State Explorer v1

macOS State Explorer is the current repository name for the public reference engine that is evolving into **WASP Prism**.

**WASP** stands for **Web Application Security & Performance**.

## Project identity

- **WASP Prism** is the future public project identity for this evidence-driven diagnostic project, with the repository rename deferred until after the Chrome Local Network reference case is solved.
- This repository remains named `macos-state-explorer` until that reference case is fully solved.
- Planned rename: `macos-state-explorer -> wasp-prism` after the Chrome Local Network reference case is complete.
- Documentation describes only the public WASP Prism project.

## Current reference case

Priority 1 is the Chrome Local Network issue:

> Explain why Chrome-related apps appear in **System Settings → Privacy & Security → Local Network** even when no `kTCCServiceLocalNetwork` rows exist in `TCC.db`, then prove the safe terminal remediation/outcome state.

The current macOS/LaunchServices implementation is the public reference engine and reference case for WASP Prism. No new Diagnostic Engines should be added until the Chrome Local Network reference case is fully solved.

Phase 2 is investigation-driven: modeled provenance must be kept separate from observed producer evidence, observed consumer evidence, inferred persistence mechanism, and unknown signals. The Chrome Local Network reference case remains the highest priority.

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
mse trace local-network ~/Desktop/mse-local-network-trace
mse report local-network --bundle ~/Desktop/mse-support-bundle
mse doctor
```

## Safety

The platform defaults to read-only diagnosis and reporting. Any mutation-capable workflow must be explicitly scoped, confirmed, audited, regression-tested, and documented. LaunchServices Phase 1 mutation remains limited to confirmed PLAN_ONLY_SAFE obsolete Chrome generations only.
