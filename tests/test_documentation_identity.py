from __future__ import annotations

from pathlib import Path


PUBLIC_PRODUCT_NAME = "Open State Diagnostics & Repair Framework"
FORBIDDEN_LEGACY_PRODUCT_NAME = "macOS " "State Explorer"
FORBIDDEN_PREVIOUS_PUBLIC_IDENTITY = ("W" "ASP Prism", "W" "ASP")
ALLOWED_TECHNICAL_IDENTIFIERS = (
    "macos-state-explorer",
    "macos_state_explorer",
    "mse",
    "https://github.com/psappz/macos-state-explorer",
)


def public_identity_paths(root: Path) -> list[Path]:
    paths = [
        root / "README.md",
        root / "ARCHITECTURE.md",
        root / "CONTRIBUTING.md",
        root / "ROADMAP.md",
        root / "SECURITY.md",
    ]
    for directory in (root / "docs", root / "tests"):
        paths.extend(path for path in directory.rglob("*") if path.is_file())
    return sorted(paths)


def test_public_documentation_uses_open_state_diagnostics_framework_name():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in public_identity_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if FORBIDDEN_LEGACY_PRODUCT_NAME in text:
            offenders.append(f"{path.relative_to(root)} contains legacy public product name")

    assert not offenders

    for path in (
        root / "README.md",
        root / "ARCHITECTURE.md",
        root / "CONTRIBUTING.md",
        root / "ROADMAP.md",
        root / "SECURITY.md",
    ):
        assert PUBLIC_PRODUCT_NAME in path.read_text(encoding="utf-8")


def test_public_markdown_does_not_use_previous_product_identity():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    markdown_paths = [
        root / "README.md",
        root / "ARCHITECTURE.md",
        root / "CONTRIBUTING.md",
        root / "ROADMAP.md",
        root / "SECURITY.md",
        *(path for path in (root / "docs").rglob("*.md")),
    ]
    for path in sorted(markdown_paths):
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_PREVIOUS_PUBLIC_IDENTITY:
            if forbidden in text:
                offenders.append(f"{path.relative_to(root)} contains previous public identity")

    assert not offenders


def test_documentation_identity_allows_technical_identifiers():
    root = Path(__file__).resolve().parents[1]
    combined_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in public_identity_paths(root)
        if path.suffix in {".md", ".py", ".txt", ".json"}
    )

    for identifier in ALLOWED_TECHNICAL_IDENTIFIERS:
        assert identifier in combined_text
