# Technology Stack

**Analysis Date:** 2026-06-16

## Languages

**Primary:**
- Python 3.12 - All application logic, execution pipeline, build scripts

**Secondary:**
- HTML/CSS/JavaScript (vanilla) - Desktop UI layer via `app/ui/index.html` (75KB single-file)

## Runtime

**Environment:**
- CPython 3.12 (pinned in CI via `actions/setup-python@v5`)

**Package Manager:**
- pip (no lockfile — dependencies installed inline in CI and locally)
- Lockfile: absent (versions specified as minimum ranges in `app/requirements.txt`)

## Frameworks

**Core:**
- pywebview >= 5.0 - Wraps the HTML/JS UI in a native desktop window; exposes Python methods to JS via `window.pywebview.api.*`

**Browser Automation:**
- playwright >= 1.40 - Chromium-based headless scraping of Axon TMS web portal (`execution/download_reports.py`)

**Build/Packaging:**
- PyInstaller >= 6.0 - Produces `--onedir` bundle (`dist/Catom/`) then wrapped in NSIS installer on Windows; `.app`/`.dmg` on macOS
- NSIS - Windows installer wrapper (`installer/Catom.nsi`)

**Testing:**
- pytest (implied by `tests/` directory with `tests/__init__.py` and `tests/test_report_editor.py`)

**Linting:**
- ruff - Config at `ruff.toml` (single `exclude = ["dist-clean"]` rule)

## Key Dependencies

**Critical:**
- `openpyxl` - Read/write `.xlsx` files; used in `execution/append_to_xlsx.py` and `execution/build_ryan_report.py` for the core report pipeline
- `pdfplumber` - Pure-Python PDF text extraction; reads Distribution PDF in `execution/build_ryan_report.py`
- `playwright` - Chromium automation for logging into and downloading CSVs from Axon TMS
- `pywebview` - Desktop window host; `app/main.py` exposes `PipelineAPI` class to the frontend JS

**Infrastructure:**
- `Pillow` - Image processing used in build pipeline (app icon handling)
- Standard library only for R2 uploads — `feedback.py` implements SigV4 signing manually with `hmac`/`hashlib`/`urllib` to avoid adding `boto3` as a runtime dependency

## Configuration

**Environment:**
- Per-customer config stored as JSON in user's app-data directory (path resolved at runtime via `platform` module)
- Key config fields: `auth.base_url`, `auth.username`, `auth.password`, `anthropic_api_key`, `schedule`
- R2 credentials baked into `app/feedback_credentials.py` at CI build time (not present in source repo)

**Build:**
- `app/build.py` - Main PyInstaller build script
- `app/__version__.py` - Single version source of truth (`2.0.0`); CI reads this to stamp the NSIS installer filename and `latest.json` update feed
- `.github/workflows/build.yml` - GitHub Actions CI; builds Windows (NSIS `.exe`) and macOS (`.app`) on release

## Platform Requirements

**Development:**
- macOS or Windows; Python 3.12; pip; Playwright Chromium browser installed via `python -m playwright install chromium`

**Production:**
- **Primary target:** Windows (NSIS installer, `.exe`)
- **Secondary:** macOS (`.app`/`.dmg`, Andrew's personal dev use only per CI comments)
- Distributed as self-contained PyInstaller bundle; no Python install required on client machine
- Auto-update: app polls `https://updates.aisimple.co/catom/latest.json` for new versions

---

*Stack analysis: 2026-06-16*
