# Coding Conventions

**Analysis Date:** 2026-06-16

## Naming Patterns

**Files:**
- `snake_case.py` for all Python modules — e.g., `build_ryan_report.py`, `append_to_xlsx.py`, `download_reports.py`
- Prefixed with verb describing action for execution scripts — e.g., `run_pipeline.py`, `run_daily_append.py`
- Test files prefixed with `test_` — e.g., `test_report_editor.py`

**Functions:**
- `snake_case` for all functions
- Leading underscore `_` for module-private/internal helpers — e.g., `_app_root()`, `_file_log()`, `_apply_slim_defaults()`, `_next_page_number()`
- Public API methods on classes use plain `snake_case` — e.g., `save_report()`, `get_report_detail()`, `load_config()`
- Verb-noun pattern for functions that act on data — e.g., `normalize_serial()`, `parse_order_master()`, `format_move_date()`, `discover_latest_file()`

**Variables:**
- `snake_case` throughout
- Module-level constants use `UPPER_SNAKE_CASE` — e.g., `APP_ROOT`, `EXECUTION`, `STATE`, `PATH_CONFIG_KEYS`, `TARGET_HEADER_ROW_1`
- Module-level mutable state prefixed with `_` — e.g., `_LOG_FILE`

**Types/Classes:**
- `PascalCase` for dataclasses and classes — e.g., `OrderMasterRecord`, `GeneratedRow`, `PipelineAPI`
- Dataclasses use `@dataclass` decorator from `dataclasses` module

## Code Style

**Formatting:**
- Ruff configured via `ruff.toml` at repo root
- `exclude = ["dist-clean"]` — only build output excluded
- No line length override found — Ruff default (88 chars)

**Type Annotations:**
- All function signatures use full type annotations — return types always explicit
- `from __future__ import annotations` at the top of every file — enables PEP 563 deferred evaluation; this is mandatory across the entire codebase
- `Path` from `pathlib` used exclusively for filesystem paths — never raw strings for paths
- Union types written with `|` operator (Python 3.10+ style, enabled by `__future__` annotations) — e.g., `dict | None`, `Path | None`, `str | int`

**Linting:**
- Ruff is the single lint+format tool
- `# type: ignore` used specifically for dual-import blocks (dev vs. frozen PyInstaller paths) — not used to suppress real type errors

## Import Organization

**Order:**
1. `from __future__ import annotations` — always first, always present
2. Standard library imports (alphabetical within group) — e.g., `import argparse`, `import csv`, `import json`
3. Third-party imports — e.g., `from openpyxl import load_workbook`, `import webview`
4. Local/relative imports — e.g., `from app.main import PipelineAPI`, `from execution.build_ryan_report import build_serial_lookup`

**Dual-import pattern for frozen builds:**
```python
try:
    from app import updater  # type: ignore
    from app.__version__ import __version__  # type: ignore
except ImportError:
    import updater  # type: ignore
    from __version__ import __version__  # type: ignore
```
This pattern appears in `app/main.py`, `app/feedback.py`, `app/updater.py` — needed because PyInstaller flattens the package structure.

**Lazy imports inside functions:**
Third-party dependencies that are optional or heavy are imported inside function bodies — e.g., `import pdfplumber` inside `parse_distribution_pdf()` in `execution/build_ryan_report.py`, `from openpyxl import load_workbook` inside `read_historical_rows()`.

**Path Aliases:** None — no package alias configuration.

## Error Handling

**Patterns:**
- Exception handling at boundaries — IO operations, subprocess calls, and config loading use `try/except`
- Broad `except Exception` used in logging/UI-facing paths where swallowing errors is intentional — e.g., `_file_log()` catches all exceptions silently to never break the app
- Specific exception types used where the failure mode is known — e.g., `except OSError:`, `except ImportError:`
- Return-value error signaling for API methods: `PipelineAPI` methods return `"ok"` on success or `{"error": "..."}` dict on failure — no exceptions raised to the JS layer
- Uncaught exceptions routed to disk log via `sys.excepthook` and `threading.excepthook` installed in `_install_excepthook()` — `app/main.py:98`

**Error return shape (PipelineAPI):**
```python
# Success
return "ok"
# Failure
return {"error": "descriptive message"}
```

## Logging

**Framework:** Custom file logger — no `logging` module used

**Pattern:**
- `_file_log(msg: str)` in `app/main.py` writes timestamped lines to `~/Library/Application Support/Catom/catom.log` (macOS) or equivalent
- Format: `[2026-06-16T14:30:00] message`
- CLI/execution scripts use `print()` with `[INFO]` prefix for console output — e.g., `print(f"[INFO] Using Summary path: {summary_path.name}")`
- No structured logging (JSON) anywhere

## Comments

**When to Comment:**
- Section dividers with dashed lines for major logical blocks — e.g., `# ---------------------------------------------------------------------------`
- Inline comments explaining non-obvious behavior — especially around PyInstaller frozen-path logic, Windows/macOS path differences, and config expansion edge cases
- Module-level docstrings explain the file's purpose and CLI usage — present in `append_to_xlsx.py` (detailed), present in `app/main.py` (brief)

**Docstrings:**
- Used on functions where behavior is non-obvious — e.g., `_xlsx_cell_to_str()`, `read_historical_rows()`, `normalize_serial()`
- Format: plain triple-quoted strings, no Sphinx/Google/NumPy style convention enforced
- Short functions often lack docstrings — no rule requiring them universally

## Function Design

**Size:** Variable — small pure functions (5–20 lines) for data normalization; large functions (50–200+ lines) for pipeline orchestration (e.g., `main()` in `build_ryan_report.py`, `PipelineAPI` methods)

**Parameters:** 
- `Path` objects for all filesystem arguments, never raw strings
- Keyword-only params not enforced — positional args used throughout
- Default values for optional normalization fallbacks — e.g., `normalize_meter(value: str, default: str = "N/A")`

**Return Values:**
- Functions always declare return types
- Pure data transformation functions return typed values directly — no mutation of inputs
- `None` returned (and typed as `X | None`) when a result may not exist — e.g., `get_report_detail()`, `discover_distribution_pdf()`

## Module Design

**Exports:** No `__all__` defined — modules export everything at module level

**Dataclasses:**
```python
@dataclass
class OrderMasterRecord:
    ...

@dataclass
class GeneratedRow:
    ...
```
Used for typed record containers in `execution/build_ryan_report.py`. No `frozen=True` or `slots=True` observed.

**Class design:** `PipelineAPI` in `app/main.py` is the single JS-facing API class — all methods callable from the webview JS bridge. Internal helpers are module-level functions prefixed with `_`.

---

*Convention analysis: 2026-06-16*
