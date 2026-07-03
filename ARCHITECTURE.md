# Architecture

Open State Diagnostics & Repair Framework is the public project name for this evidence-driven diagnostic and repair framework.

The repository currently remains named `macos-state-explorer`; that identifier is retained only for repository, package, import-path, and command-context compatibility.

Open State Diagnostics & Repair Framework separates reusable diagnostic framework capability from domain-specific engines.

## Core vs Engine principle

Core must not contain domain-specific logic.

Core owns domain-neutral capabilities:

- snapshot structure
- evidence and observation plumbing
- reporting and support-bundle plumbing
- bundle diff plumbing
- audit ingestion plumbing
- CLI wiring

Every domain-specific implementation must be an Engine. Engines own collectors, parsers, classifiers, planners, outcome models, remediation constraints, and domain-specific safety rules.

The current macOS/LaunchServices implementation is the first public reference engine and reference case.
