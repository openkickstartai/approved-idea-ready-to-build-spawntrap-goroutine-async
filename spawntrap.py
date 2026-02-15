"""SpawnTrap — False concurrency pattern static detector."""
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set


@dataclass
class Trap:
    file: str
    line: int
    rule: str
    severity: str
    message: str


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
                f"async function '{node.name}' never awaits — pure scheduling overhead"))
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                for inner in ast.walk(child):
                    if isinstance(inner, ast.Await):
                        traps.append(Trap(filepath, inner.lineno,
                            "sequential-await-loop", "error",
                            "await inside loop executes sequentially — use asyncio.gather()"))
                        break
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "gather"
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "asyncio"
                    and len(child.args) == 1 and not child.keywords):
                traps.append(Trap(filepath, child.lineno, "single-gather", "warning",
                    "asyncio.gather() with 1 argument gains no parallelism"))
    return traps


def analyze_go(source: str, filepath: str = "<stdin>") -> List[Trap]:
    traps: List[Trap] = []
    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        if re.search(r'\bgo\s+func\b', line) and i < len(lines):
            if re.search(r'<-\s*\w+', lines[i]):
                traps.append(Trap(filepath, i, "go-immediate-recv", "error",
                    "goroutine spawned then immediately blocked on channel receive"))
        if re.search(r'\.Lock\(\)', line) and i < len(lines):
            if re.search(r'defer\s+\w+\.Unlock\(\)', lines[i]):
                traps.append(Trap(filepath, i, "mutex-entire-func", "warning",
                    "mutex locks entire function body — concurrency is fully serialized"))
    return traps


def analyze_typescript(source: str, filepath: str = "<stdin>") -> List[Trap]:
    traps: List[Trap] = []
    for i, line in enumerate(source.split("\n"), 1):
        if re.search(r'Promise\.all\(\s*\[\s*[^,\]]+\s*\]\s*\)', line):
            traps.append(Trap(filepath, i, "single-promise-all", "warning",
                "Promise.all with single element provides no concurrency benefit"))
    return traps


_ANALYZERS = {
    ".py": analyze_python, ".go": analyze_go,
    ".ts": analyze_typescript, ".js": analyze_typescript,
    ".tsx": analyze_typescript, ".jsx": analyze_typescript,
}


def scan_path(path: Path, rules: Optional[Set[str]] = None) -> List[Trap]:
    traps: List[Trap] = []
    if not path.exists():
        return traps
    targets = [path] if path.is_file() else list(path.rglob("*"))
    for f in targets:
        if not f.is_file() or f.suffix not in _ANALYZERS:
            continue
        try:
            source = f.read_text(encoding="utf-8", errors="ignore")
        except (OSError, PermissionError):
            continue
        found = _ANALYZERS[f.suffix](source, str(f))
        if rules:
            found = [t for t in found if t.rule in rules]
        traps.extend(found)
    return traps
