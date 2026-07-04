from __future__ import annotations

from pathlib import Path

from macos_state_explorer.collectors.launchservices import candidate_launchservices_files


def test_candidate_launchservices_files_is_bounded_and_focused(tmp_path: Path):
    home = tmp_path / "home"
    library = home / "Library"
    ls_dir = library / "Application Support" / "com.apple.LaunchServices"
    ls_dir.mkdir(parents=True)
    (ls_dir / "com.apple.LaunchServices-foo.csstore").write_text("x")

    prefs = library / "Preferences"
    prefs.mkdir(parents=True)
    (prefs / "com.apple.LaunchServices.plist").write_text("x")
    (prefs / "unrelated.txt").write_text("x")

    files = candidate_launchservices_files(home=home, roots=[ls_dir, prefs], limit=10)

    assert any("com.apple.LaunchServices-foo.csstore" in path for path in files)
    assert any("com.apple.LaunchServices.plist" in path for path in files)
    assert not any("unrelated.txt" in path for path in files)


def test_candidate_launchservices_files_respects_limit(tmp_path: Path):
    home = tmp_path / "home"
    library = home / "Library"
    prefs = library / "Preferences"
    prefs.mkdir(parents=True)
    for index in range(5):
        (prefs / f"com.apple.LaunchServices.{index}.plist").write_text("x")

    files = candidate_launchservices_files(home=home, roots=[prefs], limit=2)

    assert len(files) == 2
