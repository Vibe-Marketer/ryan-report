<!-- refreshed: 2026-06-16 -->
# Architecture

**Analysis Date:** 2026-06-16

## System Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Desktop App (pywebview)                      │
│              `app/main.py` — PipelineAPI class                   │
│         HTML/CSS/JS UI at `app/ui/index.html`                    │
└────────────────┬───────────────────────────────────────────────-─┘
                 │ calls (in-process import or subprocess)
        ┌────────┴────────┐
        ▼                 ▼
┌───────────────┐  ┌──────────────────────────────────────────────┐
│   Download    │  │              Build / Report Layer              │
│   Layer       │  │                                               │
│ `execution/   │  │  `execution/build_ryan_report.py`             │
│  download_    │  │  `execution/append_to_xlsx.py`                │
│  reports.py`  │  │  `execution/run_daily_append.py`              │
└───────┬───────┘  └──────────────────┬────────────────────────────┘
        │                             │
        ▼                             ▼
┌───────────────┐  ┌──────────────────────────────────────────────┐
│  Axon TMS     │  │               State / Lookup Files            │
│  (external,   │  │  `state/serial_overrides.csv`                 │
│  Playwright   │  │  `state/generated_serial_lookup.csv`          │
│  browser)     │  │  `state/unresolved_serials.csv`               │
└───────────────┘  └──────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| PipelineAPI | Desktop UI bridge — exposes Python methods to JS via pywebview; orchestrates download → build → append | `app/main.py` |
| Download layer | Playwright browser automation — logs into Axon TMS, navigates menus, triggers CSV downloads | `execution/download_reports.py` |
| Report builder | Parses Axon CSVs + historical xlsx; generates Ryan-format rows; writes output CSVs | `execution/build_ryan_report.py` |
| xlsx Appender | Appends new rows to the canonical xlsx workbook with 25-row pagination and carry-over fill | `execution/append_to_xlsx.py` |
| Daily append runner | CLI entry point for scheduled/headless append-only runs | `execution/run_daily_append.py` |
| Pipeline orchestrator | CLI entry point for download + build together | `execution/run_pipeline.py` |
| Updater | Auto-update: polls JSON feed, downloads NSIS installer, applies silently | `app/updater.py` |
| Feedback | Bundles last_run + log + PDF + config and uploads to R2 for support | `app/feedback.py` |

## Pattern Overview

**Overall:** Layered pipeline — Fetch → Parse → Transform → Output

**Key Characteristics:**
- Each pipeline stage is a standalone Python module callable from CLI or in-process from the GUI
- No database; state is purely file-based (CSV + xlsx in user config dir)
- Two entry modes: GUI (pywebview desktop app) and headless/scheduled (CLI scripts)
- PyInstaller frozen build bundles a Playwright Chromium binary for zero-dependency deployment

## Layers

**GUI Layer:**
- Purpose: Wraps the pipeline in a webview desktop window; bridges JS → Python
- Location: `app/main.py`, `app/ui/index.html`
- Contains: `PipelineAPI` class with methods callable from browser JS via `window.pywebview.api.*`
- Depends on: `execution/` modules (imported in-process), `app/updater.py`, `app/feedback.py`
- Used by: End user via the Catom desktop app

**Download Layer:**
- Purpose: Browser automation against Axon TMS; exports Order Master Report CSVs
- Location: `execution/download_reports.py`
- Contains: `launch_context`, `maybe_login`, `find_axon_page`, `run_report`, `run_single_report`
- Depends on: Playwright sync API, `browser_config.json`
- Used by: `PipelineAPI._run()`, `execution/run_pipeline.py`

**Build Layer:**
- Purpose: Reads Axon CSVs + historical xlsx → computes Ryan-format rows → writes CSV output
- Location: `execution/build_ryan_report.py`
- Contains: All parsing, normalization, serial lookup, dedup, and CSV write functions
- Depends on: `openpyxl` (xlsx), `pdfplumber` (Distribution PDF), `state/` lookup CSVs
- Used by: `PipelineAPI._run()`, `execution/run_pipeline.py`

**Append Layer:**
- Purpose: Appends newly-generated rows to the live xlsx workbook with format/pagination preservation
- Location: `execution/append_to_xlsx.py`
- Contains: `_read_generated_csv`, `append_section`
- Depends on: `openpyxl`, the canonical xlsx at `historical_ryan` config path
- Used by: `PipelineAPI._append_to_xlsx()`, `execution/run_daily_append.py`

**State Layer:**
- Purpose: Persists serial → description/meter lookup and unresolved serials between runs
- Location: `state/` (repo seed) → copied to `~/.../Catom/state/` (user runtime)
- Contains: `serial_overrides.csv`, `generated_serial_lookup.csv`, `unresolved_serials.csv`
- Depends on: Nothing (pure CSV files)
- Used by: Build layer at startup and end of each run

## Data Flow

### Primary Pipeline (GUI "Run All")

1. User clicks Run in `app/ui/index.html` → JS calls `window.pywebview.api.run_pipeline("all")`
2. `PipelineAPI.run_pipeline()` spawns a background thread → `PipelineAPI._run("all")`
3. Download phase: `execution/download_reports.py` → Playwright launches Chromium, logs into Axon, triggers CSV exports → files land in `~/.../Catom/downloads/`
4. Build phase: `execution/build_ryan_report.py` reads the downloaded CSVs + `historical_ryan` xlsx + `state/` lookups
5. Parser determines input format: Summary+Detail path (new) or Order Master+New RYAN path (legacy)
6. `collect_generated_rows()` / `parse_order_master_summary()` emits `GeneratedRow` dataclass instances
7. Dedup against existing xlsx: orders already in the workbook are filtered out
8. `write_target_csv()` → `generated-ryan-report-latest-new-only.csv` in downloads dir
9. `PipelineAPI._append_to_xlsx()` → delegates to `execution/append_to_xlsx.append_section()` → appends rows into xlsx with formatting
10. `state/generated_serial_lookup.csv` and `state/unresolved_serials.csv` updated
11. Logs stream back to UI via `PipelineAPI.get_logs()` polling

### Scheduled / Headless Path

1. macOS launchd / Windows Task Scheduler calls binary with `--run-scheduled`
2. `app/main.py:main()` detects flag → `PipelineAPI()._run("all")` with no webview window
3. Same pipeline steps 3–10 as above; logs go to `~/Library/Logs/catom-report.log`

### Serial Lookup Resolution Chain

1. `state/serial_overrides.csv` — manual hand-corrections (highest priority)
2. Historical xlsx scan — most-common description/meter per serial across all year-sheets
3. `state/generated_serial_lookup.csv` — serials seen in prior generated runs
4. Fallback: emit row with blank description (never silently drop an asset)

### From/To Location Resolution Chain

1. Historical order crosswalk — repeat Order# → exact `<job>-<CITY>` Eric used historically
2. Distribution PDF asset lookup — `parse_distribution_pdf()` maps serial → `<job>-<CITY>`
3. Stopgap: `normalize_location()` — strips state code, uppercases

## Key Abstractions

**`OrderMasterRecord` dataclass:**
- Purpose: Holds one Axon order's metadata (order#, date, origin, destination, driver)
- Examples: `execution/build_ryan_report.py:55`

**`GeneratedRow` dataclass:**
- Purpose: One output row in Ryan format (truck initials, PO, date, serial, meter, description, from, to, order#)
- Examples: `execution/build_ryan_report.py:64`

**`PipelineAPI` class:**
- Purpose: Singleton bridge between pywebview JS and Python pipeline; manages run state, log buffer, config I/O
- Examples: `app/main.py:295`

## Entry Points

**Desktop app:**
- Location: `app/main.py:main()`
- Triggers: Direct execution or PyInstaller bundle launch
- Responsibilities: Creates webview window, instantiates `PipelineAPI`, starts auto-update check

**Headless scheduled run:**
- Location: `app/main.py:main()` with `--run-scheduled` argv flag
- Triggers: launchd plist / Windows Task Scheduler
- Responsibilities: Runs full pipeline silently, logs to file

**CLI pipeline:**
- Location: `execution/run_pipeline.py:main()`
- Triggers: `python execution/run_pipeline.py` or shell scripts (`run_pipeline.sh`, `run_pipeline.bat`)
- Responsibilities: Chains download + build steps with explicit path args

**CLI append-only:**
- Location: `execution/run_daily_append.py`
- Triggers: Manual or scheduled call
- Responsibilities: Appends CSV rows to xlsx without re-downloading

## Architectural Constraints

- **Threading:** pywebview runs in the main thread; all pipeline work runs in daemon threads spawned by `PipelineAPI`; `self._running` flag prevents concurrent runs
- **Frozen/dev duality:** Every module guards `getattr(sys, "frozen", False)` to locate Playwright browsers, config files, and bundled resources correctly under PyInstaller
- **Config path:** User config lives in `~/Library/Application Support/Catom/` (Mac) or `%APPDATA%/Catom/` (Windows) — never in the app bundle (which is read-only)
- **State isolation:** Repo `state/` CSVs are seed templates; actual runtime state lives in user config dir under `state/`
- **No circular imports:** GUI (`app/`) imports execution (`execution/`) in-process; execution never imports app

## Anti-Patterns

### Patching sys.argv for argparse re-use

**What happens:** `PipelineAPI._run()` patches `sys.argv` before calling `build_ryan_report.main()` in-process
**Why it's wrong:** Not thread-safe if two runs were somehow allowed simultaneously; argparse was designed for subprocess not in-process calls
**Do this instead:** Refactor `build_ryan_report.main()` to accept a parsed args object or keyword args directly; keep argparse only at the `__main__` block

### Dual import fallback pattern

**What happens:** Every frozen-path import uses `try: from app import X / except ImportError: import X`
**Why it's wrong:** Silently masks import errors in dev mode; breaks IDE navigation
**Do this instead:** Use a single import path with a sys.path manipulation at the bundle entry point

## Error Handling

**Strategy:** Log-and-continue in GUI mode; raise/exit in CLI mode

**Patterns:**
- `PipelineAPI._run()` wraps every stage in `try/except`, logs `[ERROR]` lines, returns without crashing the UI
- CLI entry points (`run_pipeline.py`) use `subprocess.run` with `check=False` then inspect returncode
- Parser functions return empty collections on missing/malformed input rather than raising
- `_file_log()` captures uncaught exceptions via `sys.excepthook` and `threading.excepthook`

## Cross-Cutting Concerns

**Logging:** `PipelineAPI._log()` writes to in-memory list (polled by JS) and `_LOG_FILE` simultaneously; CLI scripts write to stdout
**Validation:** `PipelineAPI.validate_config()` runs preflight checks before every pipeline execution; returns `{errors, warnings}` dict
**Config expansion:** `os.path.expandvars()` applied selectively — only to keys in `PATH_CONFIG_KEYS` to avoid corrupting passwords with `$$` → `$` on Windows

---

*Architecture analysis: 2026-06-16*
