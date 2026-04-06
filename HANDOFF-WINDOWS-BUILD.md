# Handoff: Catom Windows Build & Testing

## 1. Project Background

Catom is a desktop app that automates downloading reports from Axon TMS (a trucking management web app) and building a combined "Ryan report" CSV. It's built for a non-technical client who double-clicks the app, clicks "Run All", and gets their report.

The macOS version is complete, signed, notarized, and working. The Windows version needs to be built, tested, and verified end-to-end.

**Repo**: `https://github.com/Vibe-Marketer/ryan-report.git`
**Branch**: `main`
**Latest commit**: `3579b40` — "Fix packaged app: direct imports, Chrome CDP, headless-free automation"

## 2. Architecture

### Stack
- **pywebview** — native desktop window with HTML/JS UI, Python backend
- **Playwright** — browser automation via Chrome DevTools Protocol (CDP)
- **PyInstaller** — bundles everything into a standalone executable (no Python install needed on client machine)

### How it works
1. App launches a native window with `app/ui/index.html` as the UI
2. Python backend (`app/main.py`) exposes API methods callable from JS via `window.pywebview.api.*`
3. When user clicks "Run All":
   - App launches Chrome (minimized/off-screen) with CDP enabled on port 9224
   - Connects via Playwright, logs into Axon TMS, downloads 3 CSV reports
   - Builds the combined Ryan report from downloaded CSVs
   - Cleans up downloaded source files
   - Shows streaming log of every step in the UI

### Key files
| File | Purpose |
|------|---------|
| `app/main.py` | Desktop app entry point + all API methods |
| `app/ui/index.html` | Single-file UI (HTML/CSS/JS) |
| `app/build.py` | PyInstaller build script (cross-platform) |
| `execution/download_reports.py` | Playwright browser automation for Axon |
| `execution/build_ryan_report.py` | CSV processing to build the Ryan report |
| `execution/run_pipeline.py` | CLI wrapper (not used by desktop app directly) |
| `execution/browser_config.example.json` | Template config with correct action types |
| `orchestration/CATOM_SOP.md` | Client-facing SOP |

## 3. What Was Done on macOS

### Problems solved
1. **Packaged app couldn't run scripts** — PyInstaller bundles a shared library, not a Python interpreter. Subprocess calls to `python script.py` fail silently. Fixed by importing and calling modules directly instead of shelling out.
2. **Chrome blocks CDP on default profile** — Chrome refuses `--remote-debugging-port` when using its default user data directory. Fixed by auto-detecting Chrome and redirecting to a dedicated `ChromeProfile` directory inside the app's config folder.
3. **Headless Chrome renders differently** — login form fields were disabled/invisible in headless mode. Abandoned headless in favor of launching Chrome with `--start-minimized` (off-screen but renders normally).
4. **2FA handling** — Axon requires a verification code on first login from a new browser profile. The app detects when login doesn't reach the dashboard, shows a popup dialog in the Catom UI for the code, fills it via CDP, and presses Enter. 2FA trust persists — subsequent runs are fully automatic.
5. **Login form quirks** — Axon's `#user` field starts `disabled`, `#password` field starts `readonly`. Fixed by using JS to remove these attributes before filling.
6. **Credential leak** — old builds shipped `browser_config.json` with real credentials. Build now excludes it; only `browser_config.example.json` is bundled.
7. **Config persistence** — user config stored in per-user location, not inside app bundle. First-run wizard shows if no user config exists.
8. **Download timeouts** — Axon exports can be slow. Timeouts increased from 60s to 180s per report.
9. **Signing + notarization** — App signed with Developer ID, notarized by Apple, stapled. Gatekeeper approved.

### What works on macOS
- Setup wizard (browser detection, credential entry, file picker)
- Chrome automation with dedicated CDP profile
- 2FA code prompt in the app UI
- Auto-login (credentials filled, readonly/disabled fields handled via JS)
- All 3 report downloads (New RYAN, Order Master Report, audit info)
- Build step (CSV processing)
- Streaming log in UI
- Auto-cleanup of downloaded source files after build
- Settings page (all config editable)
- Airtable push
- Scheduling (launchd)
- AI troubleshooting (Claude API)
- Developer ID signed + Apple notarized

## 4. Windows-Specific Code Paths

The codebase already has Windows support in most places. Here's what exists:

### Browser detection (`app/main.py` lines ~219-245)
```
Comet:   %LOCALAPPDATA%\Programs\Comet\Comet.exe
Chrome:  %PROGRAMFILES%\Google\Chrome\Application\chrome.exe
Chrome:  %PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe
Edge:    %PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe
Brave:   %PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe
```

### User config path (`app/main.py`)
`%APPDATA%\Catom\browser_config.json`

### Chrome automation profile (`execution/download_reports.py`)
`%APPDATA%\Catom\ChromeProfile`

### Process detection (`execution/download_reports.py`)
- `tasklist /FI "IMAGENAME eq chrome.exe"` to check if running
- `taskkill /IM chrome.exe /F` to kill

### Scheduling (`app/main.py`)
- Uses `schtasks` (Windows Task Scheduler)
- Task name: `CatomReportSchedule`

### Build (`app/build.py`)
- Uses `--noconsole` flag (instead of `--windowed` on macOS)
- No `.app` bundle wrapping needed
- No codesign/notarize step
- Output: `dist/Catom/` folder with `Catom.exe`

## 5. How to Build on Windows

### Prerequisites
```
python -m pip install pywebview>=5.0 playwright>=1.40 pyinstaller>=6.0
python -m playwright install chromium
```

### Build command
```
python app/build.py
```

Output will be in `dist/Catom/` — the `Catom.exe` plus supporting files.

### For distribution
Zip the `dist/Catom/` folder into `Catom-Windows.zip`.

## 6. What Needs Testing on Windows

### Critical path (must work)
1. **Build completes** — `python app/build.py` produces a working `Catom.exe`
2. **App launches** — double-click `Catom.exe`, window appears
3. **Setup wizard** — detects installed browsers (at minimum Chrome or Edge), lets user enter credentials
4. **Browser automation** — Chrome launches minimized, connects via CDP on port 9224
5. **Chrome default profile detection** — if Chrome is selected and user data dir matches the Windows default (`%LOCALAPPDATA%\Google\Chrome\User Data`), it should redirect to `%APPDATA%\Catom\ChromeProfile`
6. **Login** — credentials filled, readonly/disabled fields handled via JS
7. **2FA** — popup dialog appears in Catom UI, user enters code, it gets filled and submitted
8. **Report downloads** — all 3 reports download with correct data (not 0 bytes)
9. **Build step** — CSV processing produces `generated-ryan-report-latest-new-only.csv` and `append-ryan-report-latest.csv`
10. **Streaming logs** — every step appears in real time in the UI
11. **Cleanup** — downloaded source files deleted after successful build

### Secondary (should work)
- Settings save/load
- File/folder picker dialogs
- "Open Folder" button
- "Get Help" button (needs Anthropic API key)
- Schedule creation via Task Scheduler
- Airtable push

### Known potential issues on Windows
1. **`--start-minimized` flag** — may behave differently on Windows Chrome. If Chrome pops up visible, try `--window-position=-32000,-32000` or investigate `SW_MINIMIZE` via `subprocess.Popen` `startupinfo`.
2. **Profile lock** — if Chrome is already running, trying to launch with `--user-data-dir` pointing to the active profile will fail with a lock error. The code handles this by killing and relaunching, but test that the kill (`taskkill`) actually works.
3. **Path separators** — the code uses `Path` objects everywhere which should handle this, but verify config paths with backslashes work correctly.
4. **`os.path.expandvars`** — used for config values like `${HOME}`. On Windows this should expand `%USERPROFILE%` etc. Verify.
5. **Playwright driver bundling** — `_find_playwright_driver()` in `build.py` looks for the driver in the playwright package. Verify it's found and bundled correctly on Windows.
6. **pywebview backend** — on Windows, pywebview uses EdgeChromium (WebView2) by default. The hidden import `webview.platforms.edgechromium` is already included. If WebView2 runtime isn't installed, pywebview falls back to MSHTML which may render the UI poorly. Most Windows 10/11 systems have WebView2.

## 7. Chrome CDP Restriction — Windows Specifics

The Chrome default data directory detection (`_is_default_chrome_dir` in `download_reports.py`) checks:
```python
os.path.join(home, "AppData", "Local", "Google", "Chrome", "User Data")
```

Verify this matches the actual default on the test machine. The automation profile goes to:
```python
%APPDATA%\Catom\ChromeProfile
```

## 8. Config Structure

The user config (`browser_config.json`) is created by the setup wizard. On Windows it should look like:
```json
{
  "browser": {
    "engine": "chromium",
    "headless": true,
    "executable_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "user_data_dir": "C:\\Users\\USERNAME\\AppData\\Roaming\\Catom\\ChromeProfile",
    "profile_directory": "Default"
  },
  "auth": {
    "base_url": "https://catom.axoneta.io/",
    "username": "Sammy",
    "password": "...",
    "manual_login_timeout_seconds": 180
  },
  "downloads": {
    "directory": "C:\\Users\\USERNAME\\Downloads\\ryan-moves-and-tests"
  },
  "reports": [...],
  "historical_ryan": "C:\\Users\\USERNAME\\path\\to\\2026 RYAN MOVES.csv"
}
```

Note: the `headless` field exists in config but is currently ignored by the code (we always launch visible+minimized). It can be removed or left — doesn't affect behavior.

## 9. Axon TMS Login Details

- **URL**: `https://catom.axoneta.io/`
- **Username**: `Sammy`
- **Password**: `RaphaSkye849$$`
- **2FA**: Sent to the account owner's phone/email. Contact the client for the code when testing.
- **Reports**: New RYAN, Order Master Report, audit info
- The Axon UI is an SPA with iframe-based navigation. Steps use JS clicks (`click_tab`, `click_menu`, `click_button`) not Playwright locators.

## 10. CI/CD

`.github/workflows/build.yml` already has a Windows build job:
```yaml
- runs-on: windows-latest
- Python 3.12
- pip install pywebview pyinstaller playwright
- python -m playwright install chromium
- python app/build.py
```

This can be triggered manually from the GitHub Actions tab or on release creation.

## 11. Files That Should NOT Be in the Build

- `execution/browser_config.json` — contains real credentials, gitignored
- `.env` — gitignored
- `__pycache__/` — excluded by build script
- `dist/`, `dist-clean/`, `build/` — gitignored

The build script (`app/build.py` line 148) explicitly excludes `browser_config.json` when staging the execution directory:
```python
shutil.copytree(
    REPO_ROOT / "execution",
    execution_stage,
    ignore=shutil.ignore_patterns("browser_config.json", "__pycache__"),
)
```

## 12. Acceptance Criteria

The Windows build is done when:
1. `Catom.exe` launches and shows the setup wizard on first run
2. Chrome is detected and selectable in the wizard
3. "Run All" connects to Chrome via CDP, logs into Axon, downloads all 3 reports, builds the Ryan report
4. Streaming log shows every step in real time
5. 2FA popup works when needed
6. Downloaded source files are cleaned up after build
7. Output CSV files are produced correctly
8. No Python install required on the client machine — everything is bundled

## 13. Contact

- **Repo owner**: Andrew Naegele (naegele412@gmail.com)
- **Apple Developer Team ID**: DTB456HJMJ
- **Axon access**: Contact Andrew for 2FA codes during testing
