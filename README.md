# 🪤 SpawnTrap

**Static detector for false concurrency patterns.** Find code that pays the full cost of async/goroutine/promise overhead but gains zero actual parallelism.

Supports **Python**, **Go**, and **TypeScript/JavaScript**.

## 🚀 Quick Start

```bash
pip install pytest  # dev dependency only
python cli.py ./your_project
```

### Examples

```bash
# Scan a directory, text output
python cli.py src/

# JSON output for tooling
python cli.py -f json src/

# SARIF for GitHub Code Scanning
python cli.py -f sarif --fail-on-error src/ > results.sarif

# Filter specific rules
python cli.py --rules async-no-await,sequential-await-loop src/
```

## 🔍 Detection Rules

| Rule ID | Lang | Severity | Description |
|---|---|---|---|
| `async-no-await` | Python | ⚠️ warning | `async def` that never `await`s — pure overhead |
| `sequential-await-loop` | Python | 🔴 error | `await` inside loop — runs sequentially, use `gather()` |
| `single-gather` | Python | ⚠️ warning | `asyncio.gather()` with 1 arg — no parallelism gain |
| `go-immediate-recv` | Go | 🔴 error | Goroutine spawned then immediately blocked on channel |
| `mutex-entire-func` | Go | ⚠️ warning | Mutex locks entire function body — serializes all access |
| `single-promise-all` | TS/JS | ⚠️ warning | `Promise.all([single])` — pointless wrapper |

## 📊 Why Pay for SpawnTrap?

False concurrency bugs are **invisible performance killers**. Your code *looks* concurrent but runs sequentially. Profilers won't catch this — they show wall-clock time, not *wasted scheduling overhead*.

SpawnTrap catches these at **code review time**, before they reach production.

## 💰 Pricing

| Feature | Free (OSS) | Pro ($19/mo) | Enterprise ($99/mo) |
|---|:---:|:---:|:---:|
| Python analysis (ast-based) | ✅ | ✅ | ✅ |
| Go analysis (regex-based) | ✅ | ✅ | ✅ |
| TS/JS analysis (regex-based) | ✅ | ✅ | ✅ |
| Text + JSON output | ✅ | ✅ | ✅ |
| SARIF output for CI/CD | — | ✅ | ✅ |
| `--fail-on-error` CI gate | — | ✅ | ✅ |
| Tree-sitter deep analysis | — | ✅ | ✅ |
| Cross-file data-flow tracing | — | — | ✅ |
| Custom rule authoring | — | — | ✅ |
| GitHub Action (pre-built) | — | ✅ | ✅ |
| Slack/Teams notifications | — | — | ✅ |
| Priority support & SLA | — | — | ✅ |

### Revenue Model

- **Free tier**: Core detection, text+JSON output — drives adoption
- **Pro** ($19/seat/mo): SARIF, CI gating, tree-sitter precision — for teams shipping async-heavy services
- **Enterprise** ($99/seat/mo): Cross-file analysis, custom rules, integrations — for platform teams

## 🏗️ CI/CD Integration

```yaml
# .github/workflows/spawntrap.yml
- name: SpawnTrap
  run: python cli.py -f sarif --fail-on-error src/ > spawntrap.sarif
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: spawntrap.sarif
```

## License

MIT — free core, paid features via license key.
