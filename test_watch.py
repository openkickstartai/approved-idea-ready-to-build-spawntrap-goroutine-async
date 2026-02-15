"""Tests for SpawnTrap watch mode — mtime detection and file filtering."""
import os
import tempfile
from pathlib import Path

from cli import collect_watch_files, detect_changed_files, get_mtimes, IGNORED_DIRS, WATCH_EXTENSIONS


def test_detect_changed_files_new_file():
    """New files appearing in new_mtimes should be detected as changed."""
    old = {Path("a.py"): 100.0, Path("b.go"): 200.0}
    new = {Path("a.py"): 100.0, Path("b.go"): 200.0, Path("c.py"): 300.0}
    changed = detect_changed_files(old, new)
    assert changed == {Path("c.py")}


def test_detect_changed_files_mtime_bump():
    """Files whose mtime changed should be detected."""
    old = {Path("a.py"): 100.0, Path("b.go"): 200.0}
    new = {Path("a.py"): 100.0, Path("b.go"): 250.0}
    changed = detect_changed_files(old, new)
    assert changed == {Path("b.go")}


def test_detect_changed_files_no_change():
    """Identical mtimes should produce empty changeset."""
    old = {Path("x.py"): 42.0}
    new = {Path("x.py"): 42.0}
    changed = detect_changed_files(old, new)
    assert changed == set()


def test_detect_changed_files_multiple_changes():
    """Multiple files changed at once."""
    old = {Path("a.py"): 1.0, Path("b.go"): 2.0, Path("c.py"): 3.0}
    new = {Path("a.py"): 1.5, Path("b.go"): 2.0, Path("c.py"): 3.5, Path("d.go"): 4.0}
    changed = detect_changed_files(old, new)
    assert changed == {Path("a.py"), Path("c.py"), Path("d.go")}


def test_collect_watch_files_filters_extensions():
    """Only .py and .go files should be collected; others ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create various files
        (Path(tmpdir) / "main.py").write_text("pass")
        (Path(tmpdir) / "server.go").write_text("package main")
        (Path(tmpdir) / "readme.md").write_text("# hi")
        (Path(tmpdir) / "style.css").write_text("body{}")
        (Path(tmpdir) / "index.ts").write_text("export {}")

        files = collect_watch_files([tmpdir])
        suffixes = {f.suffix for f in files}
        names = {f.name for f in files}

        assert ".py" in suffixes
        assert ".go" in suffixes
        assert ".md" not in suffixes
        assert ".css" not in suffixes
        assert ".ts" not in suffixes
        assert "main.py" in names
        assert "server.go" in names
        assert len(files) == 2


def test_collect_watch_files_ignores_directories():
    """__pycache__, .git, node_modules directories should be pruned."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        # Good file at root
        (base / "app.py").write_text("pass")
        # Files inside ignored directories — should not appear
        for ignored in ["__pycache__", ".git", "node_modules"]:
            d = base / ignored
            d.mkdir()
            (d / "hidden.py").write_text("pass")
            (d / "hidden.go").write_text("package x")
        # Nested valid directory should work
        sub = base / "pkg"
        sub.mkdir()
        (sub / "util.go").write_text("package pkg")

        files = collect_watch_files([tmpdir])
        names = {f.name for f in files}

        assert "app.py" in names
        assert "util.go" in names
        assert "hidden.py" not in names
        assert "hidden.go" not in names
        assert len(files) == 2


def test_get_mtimes_returns_valid_entries():
    """get_mtimes should return mtime floats for existing files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = Path(tmpdir) / "a.py"
        f1.write_text("x = 1")
        f2 = Path(tmpdir) / "b.go"
        f2.write_text("package main")

        mtimes = get_mtimes([f1, f2])
        assert f1 in mtimes
        assert f2 in mtimes
        assert isinstance(mtimes[f1], float)
        assert isinstance(mtimes[f2], float)


def test_get_mtimes_skips_missing_files():
    """get_mtimes should silently skip files that don't exist."""
    missing = Path("/nonexistent/file.py")
    mtimes = get_mtimes([missing])
    assert missing not in mtimes
    assert len(mtimes) == 0


def test_collect_watch_files_single_file():
    """Passing a single .py file directly should return it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "solo.py"
        f.write_text("pass")
        files = collect_watch_files([str(f)])
        assert len(files) == 1
        assert files[0].name == "solo.py"


def test_collect_watch_files_single_non_matching_file():
    """Passing a single .js file should return empty list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "app.js"
        f.write_text("console.log(1)")
        files = collect_watch_files([str(f)])
        assert len(files) == 0
