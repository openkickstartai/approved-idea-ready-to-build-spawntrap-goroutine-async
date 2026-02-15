#!/usr/bin/env python3
"""SpawnTrap CLI — detect false concurrency patterns in your codebase."""
import argparse
import json
import sys
from pathlib import Path

from spawntrap import scan_path

WATCH_EXTENSIONS = {".py", ".go", ".ts", ".js"}
IGNORED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}


def _to_json(traps):
    """Convert traps to JSON-serialisable list of dicts."""
    return [
        {
            "file": t.file,
            "line": t.line,
            "column": t.column,
            "rule_id": t.rule,
            "severity": t.severity,
            "message": t.message,
            "snippet": t.snippet,
        }
        for t in traps
    ]


def _sarif_rules(traps):
    """Deduplicate rules for SARIF driver.rules array."""
    seen = set()
    rules = []
    for t in traps:
        if t.rule not in seen:
            seen.add(t.rule)
            rules.append({
                "id": t.rule,
                "shortDescription": {"text": t.message},
                "defaultConfiguration": {
                    "level": "error" if t.severity == "error" else "warning"
                },
            })
    return rules


def _to_sarif(traps):
    """Convert traps to SARIF 2.1.0 object."""
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/"
                   "sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "SpawnTrap",
                        "version": "0.1.0",
                        "informationUri": "https://github.com/spawntrap/spawntrap",
                        "rules": _sarif_rules(traps),
                    }
                },
                "results": [
                    {
                        "ruleId": t.rule,
                        "level": "error" if t.severity == "error" else "warning",
                        "message": {"text": t.message},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": t.file},
                                    "region": {
                                        "startLine": t.line,
                                        "startColumn": t.column,
                                    },
                                }
                            }
                        ],
                    }
                    for t in traps
                ],
            }
        ],
    }


def _format_text(traps):
    """Format traps as human-readable text lines."""
    lines = []
    for t in traps:
        lines.append(f"{t.file}:{t.line}:{t.column}: [{t.severity}] {t.rule}: {t.message}")
        if t.snippet:
            lines.append(f"  | {t.snippet}")
    return "\n".join(lines)


def collect_watch_files(root: Path):
    """Recursively collect watchable source files under root."""
    files = []
    for p in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix in WATCH_EXTENSIONS:
            files.append(p)
    return sorted(files)


def get_mtimes(files):
    """Return dict mapping file path to mtime."""
    return {f: f.stat().st_mtime for f in files if f.exists()}


def detect_changed_files(old_mtimes, new_mtimes):
    """Return set of paths whose mtime changed or are newly added."""
    changed = set()
    for f, mtime in new_mtimes.items():
        if f not in old_mtimes or old_mtimes[f] != mtime:
            changed.add(f)
    return changed


def main():
    ap = argparse.ArgumentParser(
        prog="spawntrap",
        description="Detect false concurrency patterns that waste runtime overhead",
    )
    ap.add_argument("paths", nargs="+", help="Files or directories to scan")
    ap.add_argument(
        "-f", "--format", choices=["text", "json", "sarif"], default="text",
        help="Output format (default: text)",
    )
    ap.add_argument("--rules", help="Comma-separated rule IDs to enable (default: all)")
    ap.add_argument(
        "--fail-on-error", action="store_true",
        help="Exit with code 1 only if error-severity traps are found",
    )
    args = ap.parse_args()
    rules = set(args.rules.split(",")) if args.rules else None

    all_traps = []
    for target in args.paths:
        p = Path(target)
        if not p.exists():
            print(f"spawntrap: path not found: {target}", file=sys.stderr)
            sys.exit(2)
        all_traps.extend(scan_path(p, rules))

    # Output
    if args.format == "json":
        print(json.dumps(_to_json(all_traps), indent=2))
    elif args.format == "sarif":
        print(json.dumps(_to_sarif(all_traps), indent=2))
    else:
        output = _format_text(all_traps)
        if output:
            print(output)

    # Exit code
    if all_traps:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
