# Contributing

Thanks for helping improve macOS State Explorer.

## Project Principles

- Keep the tool read-only.
- Do not reset TCC.
- Do not delete caches.
- Do not unregister apps.
- Do not change macOS system settings.
- Prefer small, testable changes.
- Preserve CLI compatibility unless a change is explicitly planned.

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
- Put subsystem parsing and analysis in dedicated packages, such as `launchservices/`.
- Use typed models at module boundaries.
- Keep collectors focused on command execution and serialization.
- Add focused tests for parser, classifier, grouping, report, and CLI behavior.

## Pull Requests

Pull requests should include:

- A short summary of the change.
- Tests for changed behavior.
- Notes about any macOS commands used.
- Confirmation that no OS-modifying operations were added.
