# Codebase Structure

**Analysis Date:** 2026-06-16

## Directory Layout

```
ryan-report/
├── app/                        # Desktop app (pywebview GUI + entry point)
│   ├── main.py                 # PipelineAPI class + webview entry point
│   ├── updater.py              # Auto-update logic (R2 feed → NSIS installer)
│   ├── feedback.py             # Feedback bundle upload to R2
│   ├── feedback_credentials.py # R2 upload credentials (not committed)
│   ├── build.py                # PyInstaller build script
│   ├── __version__.py          # App version string
│   ├── ui/
│   │   └── index.html          # Single-file HTML/CSS/JS UI
│   ├── icon.icns / icon.png    # App icons
│   ├── entitlements.plist      # macOS code signing entitlements
│   └── cleanup.sh              # Build artifact cleanup
│
├── execution/                  # Pipeline scripts (headless + GUI-callable)
│   ├── build_ryan_report.py    # Core report builder (parse → transform → write)
│   ├── download_reports.py     # Playwright browser automation against Axon TMS
│   ├── append_to_xlsx.py       # Append rows to xlsx with format/pagination
│   ├── run_pipeline.py         # CLI: download + build in one command
│   ├── run_daily_append.py     # CLI: append-only scheduled run
│   ├── scrub_corruption.py     # Utility: repair corrupted xlsx files
│   ├── browser_config.example.json  # Config template (committed)
│   ├── run_pipeline.sh         # Shell wrapper
│   └── run_pipeline.bat        # Windows wrapper
│
├── state/                      # Persistent lookup data (seed copies)
│   ├── serial_overrides.csv    # Hand-corrected serial → description/meter
│   ├── generated_serial_lookup.csv  # Auto-built serial lookup (updated each run)
│   └── unresolved_serials.csv  # Serials with no description match
│
├── tests/
│   ├── __init__.py
│   └── test_report_editor.py   # Unit tests for report builder
│
├── tools/
│   └── catom-tickets.py        # Internal ticket management utility
│
├── skills/
│   └── append-ryan/            # Skill definition for append workflow
│       ├── SKILL.md
│       ├── evals/
│       ├── references/
│       └── scripts/
│
├── orchestration/              # Operational docs (SOPs, workflows)
│   ├── WORKFLOW.md
│   ├── CATOM_SOP.md
│   ├── CLIENT_DEPLOYMENT.md
│   └── DOE_FRAMEWORK.md
│
├── planning/                   # Specs and PRDs
│   ├── PRD-next-phase.md
│   ├── PRP-next-phase.md
│   └── SPEC-distribution-pdf-ingestion.md
│
├── .planning/
│   └── codebase/               # GSD codebase map documents (this file)
│
├── .claude/
│   └── commands/               # Claude Code custom slash commands
│
├── .github/
│   └── workflows/              # CI/CD workflows
│
├── releases/                   # Release artifacts / installer outputs
├── build/                      # PyInstaller build outputs
├── installer/                  # NSIS installer scripts
├── directives/                 # Deployment directives
├── append-ryan.skill           # Skill file reference
│
├── PRD.md                      # Top-level product requirements
├── README.md
└── ruff.toml                   # Python linter config
```

## Directory Purposes

**`app/`:**
- Purpose: Desktop application shell — pywebview window, PipelineAPI bridge, update/feedback infrastructure
- Contains: Python modules + single HTML UI file + build tooling
- Key files: `app/main.py` (1400+ lines, all GUI logic), `app/ui/index.html` (full frontend)

**`execution/`:**
- Purpose: The actual pipeline — all business logic lives here, callable from CLI or imported by GUI
- Contains: Report builder, browser downloader, xlsx appender, CLI wrappers
- Key files: `execution/build_ryan_report.py` (~1140 lines), `execution/download_reports.py` (~758 lines)

**`state/`:**
- Purpose: Seed data for serial lookups; copied to user config dir on first run
- Contains: Three CSV files that grow with each pipeline run
- Note: Runtime state lives in `~/Library/Application Support/Catom/state/` (Mac) or `%APPDATA%/Catom/state/` (Windows), NOT in the repo's `state/`

**`tests/`:**
- Purpose: Pytest test suite
- Contains: Unit tests for report builder logic
- Key files: `tests/test_report_editor.py`

**`skills/append-ryan/`:**
- Purpose: Skill definition for the append-to-xlsx workflow (PAI skill format)
- Contains: `SKILL.md`, evals, references, scripts

**`orchestration/`:**
- Purpose: Human-readable SOPs and workflow docs for operators
- Contains: Markdown docs only, no code

**`planning/`:**
- Purpose: Product specs and PRDs for upcoming work
- Contains: Markdown docs only

## Key File Locations

**Entry Points:**
- `app/main.py`: Desktop app entry — `main()` at line 1376
- `execution/run_pipeline.py`: CLI pipeline entry
- `execution/run_daily_append.py`: CLI append-only entry

**Core Logic:**
- `execution/build_ryan_report.py`: All report-building logic — parsing, normalization, serial lookup, dedup, output
- `execution/download_reports.py`: All Axon TMS browser automation

**Configuration:**
- `execution/browser_config.example.json`: Template config (committed); actual config lives in user config dir at runtime
- `state/serial_overrides.csv`: Manual serial corrections (committed as seed)

**Testing:**
- `tests/test_report_editor.py`: Primary test file

**Build:**
- `app/build.py`: PyInstaller build orchestration
- `installer/`: NSIS installer scripts for Windows distribution

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `build_ryan_report.py`, `append_to_xlsx.py`)
- Config/data: `snake_case.json` or `kebab-case.json`
- Docs: `UPPER_CASE.md` for reference docs, `kebab-case.md` for planning docs

**Functions:**
- Public pipeline functions: `snake_case` verbs (e.g., `parse_order_master`, `write_target_csv`, `collect_generated_rows`)
- Private helpers: `_leading_underscore` (e.g., `_xlsx_cell_to_str`, `_apply_slim_defaults`)
- Constants: `UPPER_CASE` (e.g., `TARGET_HEADER_ROW_1`, `SERIAL_COLUMNS`)

**Classes:**
- PascalCase (`PipelineAPI`, `OrderMasterRecord`, `GeneratedRow`)

**Dataclasses:**
- Used for typed row representations: `OrderMasterRecord`, `GeneratedRow` in `execution/build_ryan_report.py`

## Where to Add New Code

**New parsing logic (new Axon report format):**
- Implementation: `execution/build_ryan_report.py` — add `parse_*` function following the `parse_order_master_summary()` pattern
- Wire into `main()` dispatch logic in the same file

**New pipeline step (new transformation):**
- Implementation: New function in `execution/build_ryan_report.py` or new module in `execution/`
- Expose to GUI: Add method to `PipelineAPI` in `app/main.py`

**New GUI feature:**
- Backend: Method on `PipelineAPI` class in `app/main.py`
- Frontend: `app/ui/index.html` (single file)

**New CLI utility:**
- Location: `execution/` or `tools/` depending on whether it's pipeline-adjacent or standalone
- Pattern: Follow `execution/run_daily_append.py` — `argparse` + `main()` + `if __name__ == "__main__"`

**New tests:**
- Location: `tests/test_report_editor.py` (extend existing file) or `tests/test_<module>.py` for a new module

**Serial override corrections:**
- Location: `state/serial_overrides.csv` (columns: `serial,description,meter`)
- Runtime: File in user config dir `~/.../Catom/state/serial_overrides.csv`

## Special Directories

**`build/`:**
- Purpose: PyInstaller output — `dist/` + intermediate files
- Generated: Yes
- Committed: No (typically in .gitignore)

**`releases/`:**
- Purpose: Signed release binaries / installers for distribution
- Generated: Yes (by CI or build.py)
- Committed: Yes (final installers only)

**`${HOME}/` (at repo root):**
- Purpose: Browser profile data accidentally committed — Comet/Chrome cache files
- Generated: Yes (was captured during a dev session)
- Committed: Yes (should be cleaned up — see CONCERNS.md)

**`state/` (user runtime, not repo):**
- Mac: `~/Library/Application Support/Catom/state/`
- Windows: `%APPDATA%/Catom/state/`
- Purpose: Runtime serial lookup CSVs, unresolved serials — seeded from repo `state/` on first run

---

*Structure analysis: 2026-06-16*
