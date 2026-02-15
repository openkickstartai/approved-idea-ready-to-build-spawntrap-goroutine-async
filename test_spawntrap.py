"""Tests for SpawnTrap — false concurrency pattern detector."""
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
