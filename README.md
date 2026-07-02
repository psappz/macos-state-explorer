# macOS State Explorer v1

macOS State Explorer is the current repository name for the public reference engine that is evolving into **WASP Prism**.

**WASP** stands for **Web Application Security & Performance**.

## Project identity

- **WASP Prism** is the public evidence-driven diagnostic platform within the WASP ecosystem.
- This repository remains named `macos-state-explorer` until the Chrome Local Network reference case is fully solved.
- Planned rename: `macos-state-explorer -> wasp-prism` after the Chrome Local Network reference case is complete.
- **WASP Lens** remains the web/CDN-facing product.
- **WASP Prism** is the diagnostic core/platform.
- Some WASP engines and products may remain private.

## Current reference case

Priority 1 is the Chrome Local Network issue:

> Explain why Chrome-related apps appear in **System Settings → Privacy & Security → Local Network** even when no `kTCCServiceLocalNetwork` rows exist in `TCC.db`, then prove the safe terminal remediation/outcome state.

The current macOS/LaunchServices implementation is the public reference engine and reference case for WASP Prism. No new Diagnostic Engines should be added until the Chrome Local Network reference case is fully solved.

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
mse trace local-network ~/Desktop/mse-local-network-trace
mse report local-network --bundle ~/Desktop/mse-support-bundle
mse doctor
```

## Safety

The platform defaults to read-only diagnosis and reporting. Any mutation-capable workflow must be explicitly scoped, confirmed, audited, regression-tested, and documented. LaunchServices Phase 1 mutation remains limited to confirmed PLAN_ONLY_SAFE obsolete Chrome generations only.
