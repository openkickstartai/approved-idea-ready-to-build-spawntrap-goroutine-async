"""Tests for SpawnTrap — false concurrency pattern detector."""
import pytest
import tempfile
from pathlib import Path
from spawntrap import analyze_python, analyze_go, analyze_typescript, scan_path


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


def test_ts_single_promise_all():
    code = "const r = await Promise.all([fetchOne]);\n"
    traps = analyze_typescript(code)
    assert len(traps) == 1
    assert traps[0].rule == "single-promise-all"


def test_ts_multi_promise_all_clean():
    code = "const r = await Promise.all([a, b, c]);\n"
    traps = analyze_typescript(code)
    assert len(traps) == 0


def test_syntax_error_returns_empty():
    assert analyze_python("def ??? broken") == []


def test_scan_directory_finds_issues():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "bad.py").write_text("async def f():\n    return 1\n")
        traps = scan_path(Path(d))
        assert len(traps) == 1
        assert traps[0].rule == "async-no-await"


def test_scan_nonexistent_returns_empty():
    assert scan_path(Path("/no/such/path/anywhere")) == []


def test_rule_filtering():
    code = (
        "import asyncio\n"
        "async def f():\n"
        "    for x in xs:\n"
        "        await g(x)\n"
    )
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "t.py").write_text(code)
        traps = scan_path(Path(d), rules={"sequential-await-loop"})
        assert all(t.rule == "sequential-await-loop" for t in traps)


# ============================================================================
# Edge-case tests for Python async false-concurrency detection
# ============================================================================


# --- Scenario 1: async def with no await at all (basic async idle) ---

@pytest.mark.parametrize("code,func_name", [
    ("async def empty():\n    pass\n", "empty"),
    ("async def just_return():\n    return 42\n", "just_return"),
    ("async def sync_ops():\n    x = 1 + 2\n    print(x)\n    return x\n", "sync_ops"),
], ids=["pass-only", "return-only", "sync-computation"])
def test_edge_async_no_await_basic_variants(code, func_name):
    """async def bodies with zero await should all trigger async-no-await."""
    traps = analyze_python(code)
    assert any(t.rule == "async-no-await" and func_name in t.message for t in traps)


# --- Scenario 2: await only in unreachable branches ---

@pytest.mark.parametrize("code", [
    "async def f():\n    if False:\n        await something()\n    return 1\n",
    "async def f():\n    return 1\n    await something()\n",
], ids=["if-false-branch", "dead-code-after-return"])
def test_edge_await_unreachable_branch_still_seen_by_ast(code):
    """AST walker finds Await even in unreachable code — async-no-await NOT triggered.

    This documents a known limitation: the analyzer does not perform
    reachability analysis, so `if False: await x` counts as having an await.
    """
    traps = analyze_python(code)
    assert not any(t.rule == "async-no-await" for t in traps)


# --- Scenario 3: nested async calling sync function with hidden blocking ---

@pytest.mark.parametrize("code,expected_func", [
    (
        "def blocking():\n"
        "    import time; time.sleep(10)\n"
        "async def outer():\n"
        "    blocking()\n",
        "outer",
    ),
    (
        "def sync_fetch(url):\n"
        "    pass\n"
        "async def handler():\n"
        "    sync_fetch('http://example.com')\n",
        "handler",
    ),
], ids=["time-sleep-hidden", "sync-http-hidden"])
def test_edge_async_calls_sync_blocking_flagged(code, expected_func):
    """async def that only calls sync functions — triggers async-no-await."""
    traps = analyze_python(code)
    assert any(
        t.rule == "async-no-await" and expected_func in t.message for t in traps
    )


# --- Scenario 4: async for / async with wrapping only sync operations ---

@pytest.mark.parametrize("code", [
    "async def f():\n    async for item in aiter:\n        print(item)\n",
    "async def f():\n    async with mgr() as ctx:\n        x = 1 + 2\n",
], ids=["async-for-sync-body", "async-with-sync-body"])
def test_edge_async_for_with_sync_only_operations(code):
    """async for/with are not ast.Await nodes, so current impl flags async-no-await.

    This is a known false positive: AsyncFor/AsyncWith do implicit awaiting
    but the analyzer only checks for explicit ast.Await nodes.
    """
    traps = analyze_python(code)
    assert any(t.rule == "async-no-await" for t in traps)


# --- Scenario 5: empty file, syntax error file, binary file ---

@pytest.mark.parametrize("content", [
    "",
    "\n\n\n",
    "def sync(): pass\n",
    "async def broken(\n",
    "class Foo:\n  async def\n",
    "\x00\x01\x02\x03\x04",
], ids=["empty", "whitespace-only", "sync-only", "syntax-error", "incomplete-def", "null-bytes"])
def test_edge_robust_input_no_crash(content):
    """analyze_python must never crash regardless of input content."""
    traps = analyze_python(content)
    assert isinstance(traps, list)
    # All non-async or unparseable inputs should produce zero traps
    # (the async-containing syntax errors fail to parse)
    for t in traps:
        assert hasattr(t, "rule")
        assert hasattr(t, "severity")


# --- Scenario 6: type: ignore / noqa suppression comments ---

@pytest.mark.parametrize("code", [
    "async def f():  # type: ignore\n    return 1\n",
    "async def f():  # noqa\n    return 1\n",
    "async def f():  # noqa: ASYNC100\n    pass\n",
    "async def f():  # type: ignore[override]\n    x = 1\n",
], ids=["type-ignore", "noqa-bare", "noqa-specific", "type-ignore-bracket"])
def test_edge_suppression_comments_still_detected(code):
    """AST-based analysis ignores comments — traps are reported despite annotations.

    Future versions may optionally skip lines with these annotations.
    This test documents the current behavior.
    """
    traps = analyze_python(code)
    assert any(t.rule == "async-no-await" for t in traps)


# --- Additional edge-case tests ---

def test_edge_multiple_async_funcs_only_bad_ones_flagged():
    """Only async functions without await should be flagged; clean ones skipped."""
    code = (
        "async def clean():\n"
        "    await something()\n"
        "async def dirty():\n"
        "    return 42\n"
        "async def also_clean():\n"
        "    result = await other()\n"
    )
    traps = analyze_python(code)
    no_await = [t for t in traps if t.rule == "async-no-await"]
    assert len(no_await) == 1
    assert "dirty" in no_await[0].message


def test_edge_scan_path_empty_directory():
    """scan_path on an empty directory returns an empty list."""
    with tempfile.TemporaryDirectory() as d:
        traps = scan_path(Path(d))
        assert traps == []


def test_edge_scan_path_syntax_error_file():
    """scan_path should handle .py files with syntax errors without crashing."""
    with tempfile.TemporaryDirectory() as d:
        bad_file = Path(d) / "bad.py"
        bad_file.write_text("async def broken(\n", encoding="utf-8")
        traps = scan_path(Path(d))
        assert isinstance(traps, list)
        assert len(traps) == 0  # syntax error → no traps, no crash


def test_edge_scan_path_empty_py_file():
    """scan_path should handle empty .py files gracefully."""
    with tempfile.TemporaryDirectory() as d:
        empty_file = Path(d) / "empty.py"
        empty_file.write_text("", encoding="utf-8")
        traps = scan_path(Path(d))
        assert traps == []
