# Codebase Concerns

**Analysis Date:** 2026-06-16

## Tech Debt

**Duplicate scripts between `execution/` and `skills/append-ryan/scripts/`:**
- Issue: Three core scripts are copied into the skill package with divergent content. `execution/build_ryan_report.py` (1,139 lines) vs `skills/append-ryan/scripts/build_ryan_report.py` (614 lines) — the execution copy has 458 lines of additions (serial extraction regexes, `by_whom` field, VIN handling, doc comments). `execution/append_to_xlsx.py` vs `skills/append-ryan/scripts/append_to_xlsx.py` differ by 458 lines. `run_daily_append.py` appears identical but is still duplicated.
- Files: `execution/build_ryan_report.py`, `skills/append-ryan/scripts/build_ryan_report.py`, `execution/append_to_xlsx.py`, `skills/append-ryan/scripts/append_to_xlsx.py`, `execution/run_daily_append.py`, `skills/append-ryan/scripts/run_daily_append.py`
- Impact: Bug fixes applied to `execution/` scripts do not propagate to `skills/` copies (and vice versa). Features already exist in `execution/` that the skill version silently lacks.
- Fix approach: Make `skills/append-ryan/scripts/` symlink or import from `execution/`, or remove the skill copies and have the skill call `execution/` directly.

**`app/main.py` is a 1,416-line god module:**
- Issue: All PyWebView API methods, config management, file path logic, subprocess orchestration, threading, update checking, and feedback upload live in one file.
- Files: `app/main.py`
- Impact: High change-collision risk; testing any individual concern requires loading the entire module with all its side effects.
- Fix approach: Extract `PipelineAPI` class into `app/api.py`, config helpers into `app/config.py`, subprocess runner into `app/runner.py`.

**`_run_command_streaming` re-implements a timeout via wall-clock polling:**
- Issue: The timeout check inside the `for raw_line in iter(...)` loop compares `time.time() - start > timeout` on each line, so a stalled process with no output will never be killed until it produces a line.
- Files: `app/main.py` lines 747–778
- Impact: A hung subprocess (e.g., Playwright waiting on a network resource) can block the pipeline indefinitely without triggering the timeout.
- Fix approach: Run stdout reading in a separate thread and use `process.wait(timeout=...)` on the main thread, or switch to `asyncio.subprocess`.

**`self._running` flag has no threading lock:**
- Issue: `_running` is read and written from both the UI thread (via `is_running()` / `run()`) and the background daemon thread that executes the pipeline. No `threading.Lock` guards these reads/writes.
- Files: `app/main.py` lines 300, 633, 645, 989, 1094, 1153
- Impact: Race condition: user can double-click "Run" between the UI thread reading `_running=False` and the daemon thread setting it `True`, starting two parallel pipeline executions that both write to the same output files.
- Fix approach: Wrap `_running` with a `threading.Lock`; set inside the lock before spawning the thread.

## Known Bugs

**Serial extraction regex only exists in `execution/build_ryan_report.py`, not the skill copy:**
- Symptoms: When the pipeline is invoked via the `append-ryan` skill path, equipment serials embedded in text (e.g., `'87-16453 BUCKET'`, `'forks 87-11569'`) are not extracted and rows fail to match or produce empty serial fields.
- Files: `skills/append-ryan/scripts/build_ryan_report.py` (missing `_SERIAL_RE`, `_VIN_RE`, `extract_serial()`)
- Trigger: Any pipeline run through the skill scripts rather than directly via `execution/`.
- Workaround: Run `execution/build_ryan_report.py` directly.

## Security Considerations

**`app/feedback_credentials.py` ships as empty stubs in source, but R2 credentials are baked in at build time:**
- Risk: If the CI pipeline is compromised or a developer accidentally captures a built binary's contents, R2 access keys (bucket write access) are embedded in the frozen app.
- Files: `app/feedback_credentials.py`, `.github/workflows/build.yml`
- Current mitigation: Source tree values are empty strings; CI overwrites from GitHub Actions secrets. File is not gitignored.
- Recommendations: Consider scoping the R2 key to write-only on the feedback prefix only. Document in `feedback_credentials.py` that the deployed key must be restricted.

**Config file stores Axon username and password in plaintext JSON:**
- Risk: `browser_config.json` at `%APPDATA%\Catom\browser_config.json` (Windows) or `~/Library/Application Support/Catom/browser_config.json` (macOS) stores the Axon web portal password as a plain string.
- Files: `app/main.py` lines 238–269, `execution/browser_config.example.json`
- Current mitigation: Feedback uploader redacts the password before bundling (`app/feedback.py` lines 78–83).
- Recommendations: Consider using the OS keychain (Windows Credential Manager / macOS Keychain) to store credentials instead of plaintext JSON.

**Distribution PDF is fetched over HTTPS but response body is not verified:**
- Risk: `_ensure_distribution_pdf()` downloads from `https://updates.aisimple.co/catom/distribution.pdf` and writes it directly to disk without checking content type, size bounds, or a checksum.
- Files: `app/main.py` lines 180–203
- Current mitigation: HTTPS provides transport integrity. No additional validation.
- Recommendations: Add a max-size cap and content-type check before writing.

## Performance Bottlenecks

**`generated_serial_lookup.csv` is 104.6 KB and loaded on every pipeline run:**
- Problem: The serial lookup CSV in `state/` is copied to user config dir and re-read in full on every build run to resolve equipment serials.
- Files: `state/generated_serial_lookup.csv`, `app/main.py` (`_ensure_user_state`), `execution/build_ryan_report.py`
- Cause: No caching or indexing — full CSV parse on each run.
- Improvement path: Convert to a SQLite lookup table or pickle-cached dict on first load; invalidate on file mtime change.

**Playwright browser launch on every download run:**
- Problem: Each pipeline run that includes a download step launches a full Chromium browser from cold start. No browser process is reused between runs.
- Files: `execution/download_reports.py`
- Cause: `sync_playwright()` context manager is created and torn down within `_run_download`.
- Improvement path: For scheduled/daemon use, keep a persistent browser process and reconnect via CDP.

## Fragile Areas

**Header row matching in `append_to_xlsx.py` uses exact string comparison against hardcoded column headers:**
- Files: `execution/append_to_xlsx.py` lines ~30–100, `execution/build_ryan_report.py` lines 12–47
- Why fragile: `TARGET_HEADER_ROW_1` and `TARGET_HEADER_ROW_2` contain exact strings with trailing spaces (e.g., `"Job#  "`, `"Job#                          "`). If Ryan personnel rename or reformat columns in the Excel file, matching silently fails and rows are appended to wrong positions or not at all.
- Safe modification: Any column rename requires updating both header constant arrays in both `execution/build_ryan_report.py` AND `skills/append-ryan/scripts/build_ryan_report.py`.
- Test coverage: No tests cover column header matching or mismatched headers.

**`page.wait_for` timeouts in `download_reports.py` are hardcoded per UI element:**
- Files: `execution/download_reports.py`
- Why fragile: Playwright selectors and wait timeouts are tuned to Axon's current DOM. Any Axon UI update (element ID changes, page load time regressions) will cause `TimeoutError` and abort the download without a user-friendly message.
- Safe modification: Test against staging Axon instance before deploying new selector patterns.
- Test coverage: No automated tests for the download path; manually verified only.

**Page-footer corruption (`scrub_corruption.py`) is a one-shot remediation tool, not a guard:**
- Files: `execution/scrub_corruption.py`
- Why fragile: The corruption that necessitated this tool (paste-typo strings in page-footer rows) can silently recur. There is no validation step in the normal pipeline that detects and rejects corrupted rows before appending.
- Safe modification: Add a pre-append validation step in `append_to_xlsx.py` that checks page-footer row structure and raises an error rather than silently writing corrupt data.

## Test Coverage Gaps

**Download pipeline (`execution/download_reports.py`) has zero test coverage:**
- What's not tested: Browser launch, login flow, report navigation, file download, timeout handling, auth failure paths.
- Files: `execution/download_reports.py` (758 lines)
- Risk: Login selector changes, Axon session behavior changes, or timeout miscalculations go undetected until a user's scheduled run fails.
- Priority: High — this is the most externally coupled and brittle component.

**Core build logic (`execution/build_ryan_report.py`) has zero direct tests:**
- What's not tested: Serial extraction regexes, order matching logic, row deduplication, header detection, append summary generation.
- Files: `execution/build_ryan_report.py` (1,139 lines)
- Risk: Regex or matching changes silently break report accuracy. The `state/unresolved_serials.csv` (1.2 KB present) suggests real unresolved edge cases exist.
- Priority: High — pure Python, no I/O dependencies, high unit-testability with minimal setup.

**Only `PipelineAPI` report path editor methods are tested:**
- What's not tested: Config validation (`validate_config`), preflight checks (`_preflight_build_inputs`), the `_run_command_streaming` timeout logic, feedback upload, auto-update flow.
- Files: `tests/test_report_editor.py` (19 tests, 252 lines) is the only test file.
- Risk: Config validation regressions ship silently to end users.
- Priority: Medium.

## Missing Critical Features

**No rollback on failed append:**
- Problem: `append_to_xlsx.py` writes to the user's canonical workbook in place. If the script crashes mid-write (e.g., `openpyxl` raises on a corrupt cell), the workbook can be left in a partially written state.
- Blocks: Safe retry — users must restore from manual backup.
- Recommended: Copy the target xlsx to a `.bak` file before writing; delete the bak on success.

**No structured error codes returned from pipeline to UI:**
- Problem: `_run_command_streaming` captures stdout/stderr as lines and displays them verbatim. The UI has no way to distinguish "login failed" from "file not found" from "timeout" without string-matching log output.
- Files: `app/main.py` lines 747–778, `app/ui/`
- Blocks: Actionable error dialogs (e.g., "Your Axon password is wrong — go to Settings") without fragile log parsing.

---

*Concerns audit: 2026-06-16*
