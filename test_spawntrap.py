"""Tests for SpawnTrap — false concurrency pattern detector."""
import json
import subprocess
import sys
import pytest
import tempfile
from pathlib import Path
from spawntrap import analyze_python, analyze_go, analyze_typescript, scan_path, Trap


# ── Core detection tests ─────────────────────────────────────────────

def test_async_no_await_detected():
    traps = analyze_python("async def noop():\n    return 42\n")
    assert len(traps) == 1
    assert traps[0].rule == "async-no-await"
    assert traps[0].severity == "warning"
    assert "noop" in traps[0].message


def test_sequential_await_in_loop():
    code = (
        "import asyncio\n"
        "async def fetch_all(urls):\n"
        "    for url in urls:\n"
        "        result = await fetch(url)\n"
        "    return result\n"
    )
    traps = analyze_python(code)
    rules = {t.rule for t in traps}
    assert "sequential-await-loop" in rules


def test_single_gather_detected():
    code = (
        "import asyncio\n"
        "async def main():\n"
        "    r = await asyncio.gather(fetch('x'))\n"
    )
    traps = analyze_python(code)
    assert any(t.rule == "single-gather" for t in traps)


def test_proper_gather_is_clean():
    code = (
        "import asyncio\n"
        "async def main():\n"
        "    await asyncio.gather(*[fetch(u) for u in urls])\n"
    )
    traps = analyze_python(code)
    assert not any(t.rule in ("sequential-await-loop", "single-gather") for t in traps)


def test_go_immediate_recv():
    code = "func main() {\n    go func() { ch <- 1 }()\n    <-ch\n}\n"
    traps = analyze_go(code)
    assert any(t.rule == "go-immediate-recv" for t in traps)
    assert any(t.severity == "error" for t in traps)


def test_go_mutex_entire_func():
    code = "func do() {\n    mu.Lock()\n    defer mu.Unlock()\n    work()\n}\n"
    traps = analyze_go(code)
    assert any(t.rule == "mutex-entire-func" for t in traps)
    assert any(t.severity == "warning" for t in traps)


def test_ts_single_promise_all():
    code = "const result = await Promise.all([fetchData()]);\n"
    traps = analyze_typescript(code)
    assert any(t.rule == "single-promise-all" for t in traps)


def test_ts_multi_promise_all_clean():
    code = "const result = await Promise.all([fetchA(), fetchB()]);\n"
    traps = analyze_typescript(code)
    assert not any(t.rule == "single-promise-all" for t in traps)


def test_python_syntax_error_returns_empty():
    traps = analyze_python("def broken(:\n")
    assert traps == []


def test_scan_path_single_file():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("async def noop():\n    return 1\n")
        f.flush()
        traps = scan_path(Path(f.name))
        assert len(traps) == 1
        assert traps[0].rule == "async-no-await"
    import os
    os.unlink(f.name)


def test_scan_path_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "a.py").write_text("async def noop():\n    pass\n")
        (Path(tmpdir) / "b.go").write_text(
            "func main() {\n    go func() { ch <- 1 }()\n    <-ch\n}\n"
        )
        traps = scan_path(Path(tmpdir))
        rules = {t.rule for t in traps}
        assert "async-no-await" in rules
        assert "go-immediate-recv" in rules


def test_scan_path_with_rule_filter():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("async def noop():\n    return 1\n")
        f.flush()
        traps = scan_path(Path(f.name), rules={"sequential-await-loop"})
        assert len(traps) == 0
    import os
    os.unlink(f.name)


def test_trap_has_column_and_snippet():
    traps = analyze_python("async def noop():\n    return 42\n")
    assert len(traps) == 1
    assert traps[0].column >= 1
    assert "async def noop" in traps[0].snippet


def test_go_clean_code_no_traps():
    code = "func main() {\n    go doWork()\n    time.Sleep(time.Second)\n}\n"
    traps = analyze_go(code)
    assert len(traps) == 0


# ── Output format tests (≥ 4 required) ──────────────────────────────

def test_json_output_contains_required_fields():
    """JSON output must include all 7 specified fields per finding."""
    from cli import _to_json
    traps = [Trap("test.py", 10, "async-no-await", "warning",
                  "test message", 5, "async def foo():")]
    result = _to_json(traps)
    assert len(result) == 1
    item = result[0]
    required_keys = {"file", "line", "column", "rule_id", "severity", "message", "snippet"}
    assert required_keys == set(item.keys())
    assert item["file"] == "test.py"
    assert item["line"] == 10
    assert item["column"] == 5
    assert item["rule_id"] == "async-no-await"
    assert item["severity"] == "warning"
    assert item["message"] == "test message"
    assert item["snippet"] == "async def foo():"


def test_json_output_roundtrips_as_valid_json():
    """JSON output must be parseable JSON."""
    from cli import _to_json
    traps = [
        Trap("a.py", 1, "async-no-await", "warning", "msg1", 1, "code1"),
        Trap("b.py", 5, "sequential-await-loop", "error", "msg2", 8, "code2"),
    ]
    serialized = json.dumps(_to_json(traps), indent=2)
    parsed = json.loads(serialized)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["rule_id"] == "async-no-await"
    assert parsed[1]["rule_id"] == "sequential-await-loop"


def test_sarif_output_schema_and_version():
    """SARIF output must have version 2.1.0 and correct schema URI."""
    from cli import _to_sarif
    traps = [Trap("test.go", 5, "go-immediate-recv", "error",
                  "goroutine blocks", 1, "<-ch")]
    sarif = _to_sarif(traps)
    assert sarif["version"] == "2.1.0"
    assert "$schema" in sarif
    assert "sarif-schema-2.1.0" in sarif["$schema"]
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "SpawnTrap"
    assert run["tool"]["driver"]["version"] == "0.1.0"
    assert "rules" in run["tool"]["driver"]


def test_sarif_results_structure():
    """Each SARIF result must have ruleId, level, message, locations."""
    from cli import _to_sarif
    traps = [
        Trap("a.py", 1, "async-no-await", "warning", "msg1", 3, ""),
        Trap("b.go", 10, "go-immediate-recv", "error", "msg2", 1, ""),
    ]
    sarif = _to_sarif(traps)
    serialized = json.dumps(sarif, indent=2)
    parsed = json.loads(serialized)
    results = parsed["runs"][0]["results"]
    assert len(results) == 2
    for r in results:
        assert "ruleId" in r
        assert "level" in r
        assert r["level"] in ("error", "warning")
        assert "text" in r["message"]
        loc = r["locations"][0]["physicalLocation"]
        assert "artifactLocation" in loc
        assert "region" in loc
        assert "startLine" in loc["region"]
        assert "startColumn" in loc["region"]
    assert results[0]["ruleId"] == "async-no-await"
    assert results[0]["level"] == "warning"
    assert results[1]["ruleId"] == "go-immediate-recv"
    assert results[1]["level"] == "error"


def test_sarif_empty_results():
    """SARIF with no findings should still produce valid structure."""
    from cli import _to_sarif
    sarif = _to_sarif([])
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"] == []
    serialized = json.dumps(sarif)
    parsed = json.loads(serialized)
    assert parsed["version"] == "2.1.0"


def test_text_output_format():
    """Text output must include file:line:col, severity, rule, and snippet."""
    from cli import _format_text
    traps = [Trap("foo.py", 42, "async-no-await", "warning",
                  "never awaits", 5, "async def foo():")]
    output = _format_text(traps)
    assert "foo.py:42:5:" in output
    assert "[warning]" in output
    assert "async-no-await" in output
    assert "async def foo():" in output


def test_cli_exit_code_1_with_findings():
    """CLI must exit(1) when findings are detected."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("async def noop():\n    return 42\n")
        f.flush()
        fname = f.name
    try:
        result = subprocess.run(
            [sys.executable, "cli.py", "--format", "json", fname],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        findings = json.loads(result.stdout)
        assert isinstance(findings, list)
        assert len(findings) >= 1
        assert findings[0]["rule_id"] == "async-no-await"
    finally:
        os.unlink(fname)


def test_cli_exit_code_0_clean():
    """CLI must exit(0) when no findings."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def hello():\n    return 42\n")
        f.flush()
        fname = f.name
    try:
        result = subprocess.run(
            [sys.executable, "cli.py", "--format", "json", fname],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        findings = json.loads(result.stdout)
        assert findings == []
    finally:
        os.unlink(fname)


def test_cli_exit_code_2_bad_path():
    """CLI must exit(2) when path does not exist."""
    result = subprocess.run(
        [sys.executable, "cli.py", "--format", "text", "/nonexistent/path/xyz"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
