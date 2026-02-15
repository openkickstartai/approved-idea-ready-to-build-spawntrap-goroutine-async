"""SpawnTrap — False concurrency pattern static detector."""
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set


@dataclass
class Trap:
    file: str
    line: int
    rule: str
    severity: str
    message: str
    column: int = 1
    snippet: str = ""


def _get_line(source: str, lineno: int) -> str:
    """Return the source line at 1-based lineno, stripped, or empty string."""
    lines = source.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


def analyze_python(source: str, filepath: str = "<stdin>") -> List[Trap]:
    traps: List[Trap] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return traps
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if not any(isinstance(n, ast.Await) for n in ast.walk(node)):
            traps.append(Trap(filepath, node.lineno, "async-no-await", "warning",
                f"async function '{node.name}' never awaits — pure scheduling overhead",
                node.col_offset + 1, _get_line(source, node.lineno)))
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                for inner in ast.walk(child):
                    if isinstance(inner, ast.Await):
                        traps.append(Trap(filepath, inner.lineno,
                            "sequential-await-loop", "error",
                            "await inside loop executes sequentially — use asyncio.gather()",
                            inner.col_offset + 1, _get_line(source, inner.lineno)))
                        break
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "gather"
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "asyncio"
                    and len(child.args) == 1 and not child.keywords):
                traps.append(Trap(filepath, child.lineno, "single-gather", "warning",
                    "asyncio.gather() with 1 argument gains no parallelism",
                    child.col_offset + 1, _get_line(source, child.lineno)))
    return traps


def analyze_go(source: str, filepath: str = "<stdin>") -> List[Trap]:
    traps: List[Trap] = []
    lines = source.splitlines()
    # Rule: go-immediate-recv — goroutine spawn followed by immediate channel receive
    go_pattern = re.compile(r'\bgo\s+func\s*\(')
    recv_pattern = re.compile(r'<-\s*\w+')
    for i, line in enumerate(lines):
        if go_pattern.search(line):
            for j in range(i + 1, min(i + 5, len(lines))):
                if recv_pattern.search(lines[j]):
                    traps.append(Trap(filepath, j + 1, "go-immediate-recv", "error",
                        "goroutine spawned then immediately blocked on channel receive",
                        1, lines[j].strip()))
                    break
    # Rule: mutex-entire-func — mutex locks entire function body
    func_pattern = re.compile(r'^\s*func\s+')
    lock_pattern = re.compile(r'\w+\.Lock\(\)')
    defer_unlock_pattern = re.compile(r'defer\s+\w+\.Unlock\(\)')
    for i, line in enumerate(lines):
        if func_pattern.search(line):
            body_lines = []
            for j in range(i + 1, min(i + 6, len(lines))):
                stripped = lines[j].strip()
                if stripped and stripped != "{":
                    body_lines.append((j, stripped))
            if len(body_lines) >= 2:
                if (lock_pattern.search(body_lines[0][1])
                        and defer_unlock_pattern.search(body_lines[1][1])):
                    traps.append(Trap(filepath, body_lines[0][0] + 1,
                        "mutex-entire-func", "warning",
                        "mutex locks entire function body — serializes all access",
                        1, body_lines[0][1]))
    return traps


def analyze_typescript(source: str, filepath: str = "<stdin>") -> List[Trap]:
    traps: List[Trap] = []
    lines = source.splitlines()
    # Rule: single-promise-all — Promise.all with single element array
    pattern = re.compile(r'Promise\.all\(\s*\[\s*[^,\]]+\s*\]\s*\)')
    for i, line in enumerate(lines):
        m = pattern.search(line)
        if m:
            traps.append(Trap(filepath, i + 1, "single-promise-all", "warning",
                "Promise.all() with single element gains no parallelism",
                m.start() + 1, line.strip()))
    return traps


def scan_path(path: Path, rules: Optional[Set[str]] = None) -> List[Trap]:
    """Scan a file or directory for false concurrency traps."""
    traps: List[Trap] = []
    files: List[Path] = []
    if path.is_file():
        files.append(path)
    elif path.is_dir():
        for ext in ("*.py", "*.go", "*.ts", "*.js"):
            files.extend(path.rglob(ext))
    for f in sorted(files):
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        suffix = f.suffix
        if suffix == ".py":
            result = analyze_python(source, str(f))
        elif suffix == ".go":
            result = analyze_go(source, str(f))
        elif suffix in (".ts", ".js"):
            result = analyze_typescript(source, str(f))
        else:
            continue
        if rules:
            result = [t for t in result if t.rule in rules]
        traps.extend(result)
    return traps
