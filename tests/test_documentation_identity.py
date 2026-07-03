from __future__ import annotations

from pathlib import Path


def test_public_documentation_uses_open_state_diagnostics_framework_name():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in sorted(root.glob("**/*.md")):
        if any(part in {".git", ".venv", "dist", "build"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in ("WASP Prism", "WASP", "macOS State Explorer"):
            if forbidden in text:
                offenders.append(f"{path.relative_to(root)} contains {forbidden}")
    assert not offenders
    assert "Open State Diagnostics & Repair Framework" in (root / "README.md").read_text(encoding="utf-8")
