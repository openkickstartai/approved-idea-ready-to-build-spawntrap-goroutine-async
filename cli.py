#!/usr/bin/env python3
"""SpawnTrap CLI — detect false concurrency patterns in your codebase."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from spawntrap import scan_path


def _to_sarif(traps):
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/"
                   "sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "SpawnTrap", "version": "0.1.0",
            "informationUri": "https://github.com/spawntrap/spawntrap"}},
            "results": [
                {"ruleId": t.rule,
                 "level": "error" if t.severity == "error" else "warning",
                 "message": {"text": t.message},
                 "locations": [{"physicalLocation": {
                     "artifactLocation": {"uri": t.file},
                     "region": {"startLine": t.line}}}]}
                for t in traps
            ]}]
    }


def main():
    ap = argparse.ArgumentParser(prog="spawntrap",
        description="Detect false concurrency patterns that waste runtime overhead")
    ap.add_argument("paths", nargs="+", help="Files or directories to scan")
    ap.add_argument("-f", "--format", choices=["text", "json", "sarif"], default="text")
    ap.add_argument("--rules", help="Comma-separated rule IDs to enable (default: all)")
    ap.add_argument("--fail-on-error", action="store_true",
        help="Exit with code 1 if any error-severity trap is found")
    args = ap.parse_args()
    rules = set(args.rules.split(",")) if args.rules else None
    all_traps = []
    for target in args.paths:
        p = Path(target)
        if not p.exists():
            print(f"spawntrap: path not found: {target}", file=sys.stderr)
            sys.exit(2)
        all_traps.extend(scan_path(p, rules))
    if args.format == "json":
        print(json.dumps([asdict(t) for t in all_traps], indent=2))
    elif args.format == "sarif":
        print(json.dumps(_to_sarif(all_traps), indent=2))
    else:
        for t in all_traps:
            icon = "\U0001f534" if t.severity == "error" else "\u26a0\ufe0f "
            print(f"  {icon} {t.file}:{t.line}  [{t.rule}]  {t.message}")
        errors = sum(1 for t in all_traps if t.severity == "error")
        warns = len(all_traps) - errors
        summary = f"SpawnTrap: {len(all_traps)} issue(s) ({errors} error, {warns} warning)"
        print(f"\n  {summary}" if all_traps else "  \u2705 No false concurrency patterns found.")
    if args.fail_on_error and any(t.severity == "error" for t in all_traps):
        sys.exit(1)


if __name__ == "__main__":
    main()
