"""Ryan Report -- Desktop App

A simple desktop UI for running the Ryan report pipeline.
Double-click to launch, click a button to run.
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import webview

# Updater module — auto-update polls a JSON feed and runs the new NSIS
# installer silently. Importable both as `app.updater` (dev) and `updater`
# (frozen build) — the inner module handles the dual import.
try:
    from app import updater  # type: ignore
    from app.__version__ import __version__  # type: ignore
except ImportError:
    import updater  # type: ignore
    from __version__ import __version__  # type: ignore


# ---------------------------------------------------------------------------
# Path resolution -- works both in dev and when frozen by PyInstaller.
# ---------------------------------------------------------------------------

def _app_root() -> Path:
    """Return the project root (one level above app/)."""
    if getattr(sys, "frozen", False):
        # PyInstaller puts the exe in dist/; the repo is bundled inside _MEIPASS.
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _ui_path() -> str:
    return str(Path(__file__).resolve().parent / "ui" / "index.html")


APP_ROOT = _app_root()
EXECUTION = APP_ROOT / "execution"
STATE = APP_ROOT / "state"
PATH_CONFIG_KEYS = {
    "directory",
    "executable_path",
    "historical_ryan",
    "path",
    "user_data_dir",
}


def _user_config_dir() -> Path:
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Catom"
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return appdata / "Catom"
    return home / ".config" / "catom"


# ---------------------------------------------------------------------------
# File logging — writes every UI log line + uncaught exceptions to disk so we
# can debug failures without rebuilding with --console mode.
# ---------------------------------------------------------------------------

_LOG_FILE: Path | None = None


def _log_file_path() -> Path:
    p = _user_config_dir() / "catom.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _file_log(msg: str) -> None:
    global _LOG_FILE
    if _LOG_FILE is None:
        _LOG_FILE = _log_file_path()
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass  # never let logging break the app


def _install_excepthook() -> None:
    """Route any uncaught exception to the log file."""
    def _hook(exc_type, exc_value, tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, tb))
        _file_log(f"UNCAUGHT EXCEPTION:\n{msg}")
        sys.__excepthook__(exc_type, exc_value, tb)
    sys.excepthook = _hook

    # Thread-level uncaught exceptions (Python 3.8+).
    def _thread_hook(args):
        msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        _file_log(f"UNCAUGHT THREAD EXCEPTION ({args.thread.name}):\n{msg}")
    threading.excepthook = _thread_hook


def _user_config_path() -> Path:
    return _user_config_dir() / "browser_config.json"


def _user_state_dir() -> Path:
    return _user_config_dir() / "state"


def _ensure_user_state() -> Path:
    user_state = _user_state_dir()
    user_state.mkdir(parents=True, exist_ok=True)
    for name in (
        "serial_overrides.csv",
        "generated_serial_lookup.csv",
        "unresolved_serials.csv",
    ):
        src = STATE / name
        dest = user_state / name
        if src.exists() and not dest.exists():
            shutil.copy2(src, dest)
    return user_state


def _template_config_path() -> Path:
    example = EXECUTION / "browser_config.example.json"
    if example.exists():
        return example
    return EXECUTION / "browser_config.json"


# ---------------------------------------------------------------------------
# Managed pipeline folders -- all under %APPDATA%\Catom\ on Windows so we
# never ask the user where things go and we always know where to find them
# for the feedback bundle.
# ---------------------------------------------------------------------------

DISTRIBUTION_PDF_URL = "https://updates.aisimple.co/catom/distribution.pdf"


def _managed_downloads_dir() -> Path:
    p = _user_config_dir() / "downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _managed_distribution_dir() -> Path:
    p = _user_config_dir() / "distribution"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _managed_last_run_dir() -> Path:
    p = _user_config_dir() / "last_run"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _managed_feedback_dir() -> Path:
    p = _user_config_dir() / "feedback"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _distribution_pdf_path() -> Path:
    return _managed_distribution_dir() / "distribution.pdf"


def _ensure_distribution_pdf(force: bool = False) -> Path | None:
    """Fetch the canonical Distribution PDF from R2 if we don't have it.

    Lazy: only downloads if missing or `force=True`. Returns the path on success,
    None on failure (network down etc.) — the pipeline can keep running without
    the PDF, it just loses asset->job# crosswalk for new assets.
    """
    dest = _distribution_pdf_path()
    if dest.exists() and not force:
        return dest
    try:
        import urllib.request
        req = urllib.request.Request(
            DISTRIBUTION_PDF_URL,
            headers={"User-Agent": f"Catom/{__version__}"},
        )
        # Use the certifi-backed SSL context: a frozen Windows build has no
        # system CA store, so a bare urlopen would fail TLS verification here
        # exactly like the update check did.
        with updater._urlopen(req, timeout=30) as resp:
            data = resp.read()
        dest.write_bytes(data)
        _file_log(f"[INFO] Distribution PDF fetched ({len(data)} bytes) -> {dest}")
        return dest
    except Exception as exc:
        _file_log(f"[WARN] Could not fetch Distribution PDF: {exc}")
        return None


def _autodetect_browser_path() -> str:
    """Find the first installed Chromium-family browser. Used to skip the
    browser-picker wizard step entirely."""
    system = platform.system()
    if system == "Windows":
        program_files   = os.environ.get("PROGRAMFILES",       r"C:\Program Files")
        program_files_x = os.environ.get("PROGRAMFILES(X86)",  r"C:\Program Files (x86)")
        local_app_data  = os.environ.get("LOCALAPPDATA",       "")
        candidates = [
            Path(program_files)   / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files_x) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files_x) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(program_files)   / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            Path(local_app_data)  / "Programs" / "Comet" / "Comet.exe" if local_app_data else None,
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ]
    else:
        candidates = [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium")]
    for cand in candidates:
        if cand and cand.exists():
            return str(cand)
    return ""


def _apply_slim_defaults(cfg: dict) -> dict:
    """Backfill only the things the user shouldn't have to think about.

    Per-customer secrets (Axon URL + username + password) are captured by the
    wizard and stored in the user's config file. They are NEVER pre-filled or
    embedded in the build.

    What we DO backfill:
      - First installed Chromium-family browser (auto-detected at runtime)
      - Managed downloads/distribution/last_run dirs under %APPDATA%\\Catom\\
      - Sensible Axon base_url default (catom.axoneta.io — current customer's
        subdomain; overridable in the wizard)
      - Distribution PDF auto-fetched from R2 if missing

    Credentials stay empty until the user fills them in the wizard or Settings.
    """
    cfg.setdefault("auth", {})
    cfg["auth"].setdefault("base_url", "https://catom.axoneta.io/")
    cfg["auth"].setdefault("username", "")
    cfg["auth"].setdefault("password", "")
    cfg["auth"].setdefault("manual_login_timeout_seconds", 300)

    cfg.setdefault("browser", {})
    cfg["browser"].setdefault("engine", "chromium")
    cfg["browser"].setdefault("headless", True)
    if not cfg["browser"].get("executable_path"):
        cfg["browser"]["executable_path"] = _autodetect_browser_path()
    cfg["browser"].setdefault("user_data_dir", str(_user_config_dir() / "ChromeProfile"))
    cfg["browser"].setdefault("profile_directory", "Default")

    cfg.setdefault("downloads", {})
    cfg["downloads"]["directory"] = str(_managed_downloads_dir())

    cfg.setdefault("historical_ryan", "")
    cfg.setdefault("anthropic_api_key", "")
    return cfg


def _legacy_bundled_config_paths() -> list[Path]:
    return [
        EXECUTION / "browser_config.json",
        APP_ROOT / "_internal" / "execution" / "browser_config.json",
        APP_ROOT / "app" / "_internal" / "execution" / "browser_config.json",
    ]


def _remove_legacy_bundled_configs() -> None:
    for path in _legacy_bundled_config_paths():
        try:
            if path.exists():
                path.unlink()
        except OSError:
            # Ignore cleanup failures. The app should still prefer user config.
            pass


# ---------------------------------------------------------------------------
# Pipeline API -- exposed to the webview JS layer.
# ---------------------------------------------------------------------------

class PipelineAPI:
    """Methods callable from the browser UI via window.pywebview.api.*"""

    def __init__(self, window: webview.Window | None = None):
        self._window = window
        self._running = False
        self._log_lines: list[str] = []
        _remove_legacy_bundled_configs()

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    # -- Auto-update bridge --

    def get_app_version(self) -> str:
        """Current installed Catom version. Shown in the UI footer."""
        return __version__

    def check_for_update(self) -> dict | None:
        """Synchronous update check. Returns {'version','url','notes'} or None."""
        return updater.ui_check_for_update()

    def download_update(self, url: str) -> dict:
        """Download installer to %TEMP%. Returns {'ok','path','error'}."""
        return updater.ui_download_update(url)

    def apply_update(self) -> dict:
        """Launch downloaded installer silently and exit. Only returns on failure."""
        return updater.ui_apply_update()

    def _start_background_update_check(self) -> None:
        """Kicked off from main() after the window is created. Fires the banner
        via JS if an update is available. Silently does nothing on failure."""
        if not self._window:
            return

        def _on_available(info: dict) -> None:
            try:
                import json as _json
                self._window.evaluate_js(
                    f"window.showUpdateBanner && window.showUpdateBanner({_json.dumps(info)})"
                )
            except Exception:
                pass

        updater.check_async(_on_available)

    # -- Missing file bridge --

    def _request_missing_file(self, path: str) -> str:
        """Ask the UI what to do about a missing file. Blocks pipeline thread.
        Returns: a file path, 'new', or 'cancel'."""
        if not self._window:
            return "new"
        self._missing_file_result: str | None = None
        self._missing_file_event = threading.Event()
        import json as _json
        self._window.evaluate_js(
            f"showMissingFile({_json.dumps(path)}).then(r => window.pywebview.api.submit_missing_file(r))"
        )
        self._missing_file_event.wait(timeout=300)
        return (self._missing_file_result or "cancel").strip()

    def submit_missing_file(self, result: str) -> str:
        """Called from JS with a file path, 'new', or 'cancel'."""
        self._missing_file_result = result
        if hasattr(self, "_missing_file_event"):
            self._missing_file_event.set()
        return "ok"

    # -- Config helpers --

    def get_config_path(self) -> str:
        p = _user_config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)

    def load_config(self) -> dict[str, Any]:
        user_path = Path(self.get_config_path())
        source_path = user_path if user_path.exists() else _template_config_path()
        if not source_path.exists():
            return _apply_slim_defaults({})
        with source_path.open("r") as f:
            cfg = json.load(f)
        # Report automation steps are APP-MANAGED, not user data: the Axon
        # navigation/export sequence is defined canonically in the bundled
        # template. Always overwrite the user's "reports" with the template's so
        # fixes to the export flow (e.g. preset selection, dual Detail+Summary
        # export) reach existing installs on the next launch instead of being
        # frozen in a stale on-disk config. Auth/historical/schedule are left
        # untouched — only the reports list is force-managed.
        if source_path != _template_config_path():
            try:
                tmpl = _template_config_path()
                if tmpl.exists():
                    with tmpl.open("r") as tf:
                        canonical = json.load(tf)
                    if isinstance(canonical.get("reports"), list):
                        cfg["reports"] = canonical["reports"]
            except (OSError, ValueError):
                pass  # fall back to the user config's reports
        # Expand ${HOME}/%USERPROFILE% only in path-like fields. On Windows,
        # expandvars turns a literal "$$" into "$", which corrupts passwords.
        def _exp(o: Any, key: str = "") -> Any:
            if isinstance(o, str):
                if key in PATH_CONFIG_KEYS:
                    return os.path.expandvars(o)
                return o
            if isinstance(o, dict):
                return {k: _exp(v, k) for k, v in o.items()}
            if isinstance(o, list):
                return [_exp(v, key) for v in o]
            return o
        return _apply_slim_defaults(_exp(cfg))

    def save_config(self, cfg: dict) -> str:
        p = Path(self.get_config_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        # Always re-apply slim defaults so we never persist missing fields. The
        # only thing the user controls is historical_ryan + (optionally)
        # anthropic_api_key + schedule. Everything else is auto-managed.
        cfg = _apply_slim_defaults(cfg)
        with p.open("w") as f:
            json.dump(cfg, f, indent=2)
        # Kick off PDF fetch on first save (the wizard's terminal action) so the
        # pipeline has it ready for the very first run.
        threading.Thread(target=lambda: _ensure_distribution_pdf(force=False),
                         daemon=True).start()
        return "ok"

    # -- Managed pipeline folders + Distribution PDF + Feedback --

    def get_managed_paths(self) -> dict[str, str]:
        """Surface where Catom keeps everything, so Settings can offer Open Folder buttons."""
        return {
            "config_dir":      str(_user_config_dir()),
            "downloads":       str(_managed_downloads_dir()),
            "distribution":    str(_managed_distribution_dir()),
            "last_run":        str(_managed_last_run_dir()),
            "feedback":        str(_managed_feedback_dir()),
            "log_file":        str(_log_file_path()),
            "distribution_pdf": str(_distribution_pdf_path()),
        }

    def open_folder(self, which: str) -> str:
        """Open a managed folder in the OS file manager. `which` is one of the
        keys returned by get_managed_paths (or 'workbook' for the directory the
        user's xlsx lives in)."""
        cfg = self.load_config()
        paths = self.get_managed_paths()
        if which == "workbook":
            hist = cfg.get("historical_ryan", "")
            target = str(Path(hist).parent) if hist else paths["config_dir"]
        else:
            target = paths.get(which, paths["config_dir"])
        if not Path(target).exists():
            Path(target).mkdir(parents=True, exist_ok=True)
        try:
            if platform.system() == "Windows":
                os.startfile(target)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                import subprocess
                subprocess.Popen(["open", target])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", target])
            return "ok"
        except Exception as exc:
            return f"error: {exc}"

    def distribution_pdf_status(self) -> dict[str, Any]:
        p = _distribution_pdf_path()
        if not p.exists():
            return {"exists": False, "path": str(p), "size_bytes": 0, "mtime": "", "age_days": None}
        st = p.stat()
        age_days = int((datetime.datetime.now().timestamp() - st.st_mtime) // 86400)
        return {
            "exists": True,
            "path": str(p),
            "size_bytes": st.st_size,
            "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "age_days": age_days,
        }

    def get_last_run_warnings(self) -> dict[str, Any]:
        """How many moves in the most recent run had no job number. The UI polls
        this after a run to decide whether to show the 'upload a fresh PDF' nudge."""
        return {"missing_job_numbers": getattr(self, "_last_run_missing_jobs", 0)}

    @staticmethod
    def _count_missing_job_numbers(csv_path: str) -> int:
        """Count generated rows whose From or To is a bare town (no job# prefix,
        no shop '-CITY' suffix). That's the signal the Distribution PDF is stale
        or missing coverage for those assets."""
        import csv as _csv
        import re as _re
        path = Path(csv_path)
        if not path.exists():
            return 0
        jobpat = _re.compile(r"^\d{3,4}\.\d")
        def bare(v: str) -> bool:
            v = (v or "").strip()
            return bool(v) and not jobpat.match(v) and "-" not in v
        n = 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for row in _csv.reader(fh):
                    if len(row) >= 10 and row[0].strip().isdigit():
                        if bare(row[8]) or bare(row[9]):  # From / To
                            n += 1
        except OSError:
            return 0
        return n

    def refresh_distribution_pdf(self) -> dict[str, Any]:
        """Force-redownload the Distribution PDF from R2. Used by Settings."""
        result = _ensure_distribution_pdf(force=True)
        if result:
            return {"ok": True, "path": str(result), "size_bytes": result.stat().st_size}
        return {"ok": False, "error": "Could not download from updates.aisimple.co"}

    def upload_distribution_pdf(self, source_path: str) -> dict[str, Any]:
        """Copy a user-picked PDF into the managed distribution folder. Used
        when Eric has a fresher PDF than what's on R2."""
        src = Path(source_path)
        if not src.exists():
            return {"ok": False, "error": f"File not found: {source_path}"}
        if src.suffix.lower() != ".pdf":
            return {"ok": False, "error": "Only .pdf files are accepted."}
        dest = _distribution_pdf_path()
        try:
            shutil.copy2(src, dest)
            return {"ok": True, "path": str(dest), "size_bytes": dest.stat().st_size}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def send_feedback(self, message: str) -> dict[str, Any]:
        """Bundle last_run + log + PDF + redacted config + Eric's note and upload to R2.

        See app/feedback.py for the implementation.
        """
        try:
            from app import feedback  # type: ignore
        except ImportError:
            import feedback  # type: ignore
        return feedback.build_and_upload_bundle(message=message, api=self)

    def validate_config(self) -> dict[str, list[str]]:
        cfg = self.load_config()
        errors: list[str] = []
        warnings: list[str] = []

        auth = cfg.get("auth", {})
        downloads = cfg.get("downloads", {})

        if not auth.get("base_url"):
            errors.append("Axon base URL is missing.")
        if not auth.get("username"):
            errors.append("Axon username is missing.")
        if not auth.get("password"):
            errors.append("Axon password is missing.")

        download_dir = downloads.get("directory", "")
        if not download_dir:
            errors.append("Download directory is missing.")
        else:
            dl = Path(download_dir)
            try:
                dl.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                errors.append(f"Could not create download directory: {dl} ({exc})")

        historical = cfg.get("historical_ryan", "")
        if not historical:
            warnings.append("Historical Ryan file is not set -- all orders will be treated as new.")
        elif not Path(historical).exists():
            warnings.append(f"Historical Ryan file not found: {historical} -- you'll be asked to locate it.")

        reports = [r for r in cfg.get("reports", []) if r.get("enabled", True)]
        if not reports:
            errors.append("No enabled reports are configured.")

        return {"errors": errors, "warnings": warnings}

    # -- Auto-detection --

    def is_configured(self) -> bool:
        """Return True only when the user has finished the wizard.

        Configured = wizard saved both Axon credentials AND the historical
        Ryan xlsx path. Either alone is incomplete.
        """
        user_path = Path(self.get_config_path())
        if not user_path.exists():
            return False
        cfg = self.load_config()
        auth = cfg.get("auth", {})
        has_creds = bool(auth.get("username")) and bool(auth.get("password"))
        has_xlsx  = bool(cfg.get("historical_ryan"))
        return has_creds and has_xlsx

    def get_default_download_dir(self) -> str:
        return str(Path.home() / "Downloads" / "ryan-moves-and-tests")

    # -- File/folder browser --

    def pick_folder(self) -> str | None:
        result = self._window.create_file_dialog(
            webview.FOLDER_DIALOG, allow_multiple=False
        )
        if result and len(result) > 0:
            return result[0]
        return None

    def pick_file(self, title: str = "Select file") -> str | None:
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Spreadsheets (*.csv;*.xlsx;*.xls)", "CSV Files (*.csv)", "Excel Files (*.xlsx;*.xls)", "All Files (*.*)"),
        )
        if result and len(result) > 0:
            return result[0]
        return None

    def ensure_folder(self, path: str) -> str:
        """Create a folder if it doesn't exist. Returns 'ok'."""
        Path(path).mkdir(parents=True, exist_ok=True)
        return "ok"

    # -- Hours saved tracking --

    def get_hours_saved(self) -> float:
        """Return total hours saved from config."""
        cfg = self.load_config()
        return float(cfg.get("hours_saved", 0))

    def reset_hours_saved(self) -> str:
        """Reset the hours saved counter to 0."""
        cfg = self.load_config()
        cfg["hours_saved"] = 0
        self.save_config(cfg)
        return "ok"

    def _increment_hours_saved(self, hours: float = 3.0) -> float:
        """Add hours to the saved counter and return new total."""
        cfg = self.load_config()
        current = float(cfg.get("hours_saved", 0))
        new_total = current + hours
        cfg["hours_saved"] = new_total
        self.save_config(cfg)
        return new_total

    # -- Pipeline execution --

    def is_running(self) -> bool:
        return self._running

    def get_logs(self) -> list[str]:
        """Return and flush accumulated log lines."""
        lines = self._log_lines[:]
        self._log_lines.clear()
        return lines

    def run_pipeline(self, mode: str = "all") -> str:
        """Run the pipeline in a background thread. mode: all|download|build"""
        if self._running:
            return "already running"
        self._running = True
        self._log_lines.clear()
        t = threading.Thread(target=self._run, args=(mode,), daemon=True)
        t.start()
        return "started"

    def _log(self, msg: str) -> None:
        self._log_lines.append(msg)
        _file_log(msg)

    def _append_to_xlsx(self, historical_path: str, new_rows_csv: str) -> None:
        """Delegate to the production carry-over appender so the GUI 'Run All'
        path produces the same skill-quality output (25-row pagination,
        carry-over fill, format preservation) as the daily scheduled run.

        Replaces an earlier naive ws.append() loop that bypassed all of
        execution/append_to_xlsx.py's logic and silently produced an xlsx
        with no formatting and no sectioning.
        """
        new_csv = Path(new_rows_csv)
        if not new_csv.exists() or new_csv.stat().st_size == 0:
            return

        hist = Path(historical_path)
        xlsx_path = hist if hist.suffix.lower() == ".xlsx" else hist.with_suffix(".xlsx")

        if not xlsx_path.exists():
            self._log(
                f"[WARN] {xlsx_path.name} not found — carry-over appender requires "
                f"the canonical workbook to exist. Skipping append."
            )
            return

        try:
            from execution.append_to_xlsx import _read_generated_csv, append_section
        except ImportError as exc:
            self._log(f"[ERROR] Could not import production appender: {exc}")
            return

        try:
            rows = _read_generated_csv(new_csv)
        except Exception as exc:
            self._log(f"[ERROR] Failed to read {new_csv.name}: {exc}")
            return

        if not rows:
            self._log("[OK] No new rows to append.")
            return

        try:
            summary = append_section(xlsx_path, rows)
        except RuntimeError as exc:
            # Excel-lock or sheet-missing — surface plainly to the user.
            self._log(f"[ERROR] {exc}")
            return
        except Exception as exc:
            self._log(f"[ERROR] Append failed: {exc}")
            return

        self._log(
            f"[OK] Appended {summary['appended']} row(s) to {xlsx_path.name} "
            f"(carry-over: {summary['carry_over_filled']}, "
            f"new sections: {summary['new_sections_written']}, "
            f"skipped dupes: {summary['skipped_dupe']})"
        )
        for sec in summary.get("completed_sections", []):
            self._log(f"[OK] Section completed (page {sec.get('page_number','?')}, 25 rows).")

    def _latest_matching_file(self, directory: Path, prefix: str) -> Path | None:
        matches = sorted(
            directory.glob(f"{prefix}*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    def _preflight_build_inputs(self, cfg: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        dl_dir = Path(cfg.get("downloads", {}).get("directory", ""))
        if not dl_dir.exists():
            return [f"Download directory does not exist: {dl_dir}"]

        # Historical file is handled separately with the missing file dialog.
        # Don't block the build here -- just check for required source CSVs.
        # New RYAN is no longer downloaded; the build uses the Order Master Summary export.
        required_prefixes = ["Order Master Report", "New RYAN"]
        for prefix in required_prefixes:
            if not self._latest_matching_file(dl_dir, prefix):
                errors.append(f"Required source CSV not found in downloads: {prefix}*.csv")

        return errors

    def _download_timeout_seconds(self, cfg: dict[str, Any]) -> int:
        auth = cfg.get("auth", {})
        reports = [r for r in cfg.get("reports", []) if r.get("enabled", True)]
        manual_login_timeout = int(auth.get("manual_login_timeout_seconds", 180))
        per_report_budget = 120
        launch_buffer = 180
        return max(900, manual_login_timeout + (len(reports) * per_report_budget) + launch_buffer)

    def _build_timeout_seconds(self) -> int:
        return 900

    def _run_command_streaming(
        self,
        cmd: list[str],
        timeout: int,
        cwd: Path | None = None,
    ) -> int:
        import subprocess

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        start = time.time()
        assert process.stdout is not None
        try:
            for raw_line in iter(process.stdout.readline, ""):
                line = raw_line.rstrip("\n")
                if line:
                    self._log(line)
                if time.time() - start > timeout:
                    process.kill()
                    raise subprocess.TimeoutExpired(cmd, timeout)

            return process.wait(timeout=max(1, int(timeout - (time.time() - start))))
        except subprocess.TimeoutExpired:
            process.kill()
            raise
        finally:
            if process.stdout:
                process.stdout.close()

    def _run(self, mode: str) -> None:
        try:
            config = self.get_config_path()
            cfg = self.load_config()

            validation = self.validate_config()
            for warning in validation["warnings"]:
                self._log(f"[WARN] {warning}")
            if validation["errors"]:
                for error in validation["errors"]:
                    self._log(f"[ERROR] {error}")
                self._log("[ERROR] Preflight validation failed. Fix settings and try again.")
                return

            # Import the execution modules -- works in both dev and frozen modes.
            sys.path.insert(0, str(EXECUTION.parent))
            from execution.download_reports import load_config as dl_load_config
            from execution.download_reports import (
                close_session,
                find_axon_page,
                launch_context,
                maybe_login,
                run_report,
            )

            if mode in ("all", "download"):
                self._log("[1/2] Downloading reports from Axon...")
                try:
                    dl_cfg = dl_load_config(Path(config))
                    downloads_dir = Path(dl_cfg["downloads"]["directory"])
                    downloads_dir.mkdir(parents=True, exist_ok=True)

                    # Scratch-clean: remove leftover CSVs from a prior (possibly
                    # failed) run so a download failure can't silently reuse stale
                    # data and build on yesterday's report. The downloads dir holds
                    # only transient inputs/outputs; the historical workbook lives
                    # elsewhere as .xlsx, so this never touches real data.
                    for _stale in downloads_dir.glob("*.csv"):
                        try:
                            _stale.unlink()
                        except OSError:
                            pass

                    self._log("[INFO] Launching bundled browser...")
                    context, pw = launch_context(dl_cfg)
                    self._log("[INFO] Browser ready")

                    try:
                        page = find_axon_page(context, dl_cfg["auth"]["base_url"])
                        page.set_viewport_size({"width": 1600, "height": 1000})
                        self._log("[INFO] Logging in to Axon...")
                        maybe_login(page, dl_cfg)
                        self._log("[INFO] Logged in to Axon")

                        self._downloaded_files: list[Path] = []
                        for report in dl_cfg["reports"]:
                            if report.get("enabled", True) is False:
                                continue
                            self._log(f"[INFO] Downloading {report['name']}...")
                            try:
                                results = run_report(page, report, downloads_dir)
                                # run_report now returns list[Path] (one entry per
                                # `triggers_download` step). Order Master pulls 2
                                # presets in one navigation pass.
                                if isinstance(results, list):
                                    for r in results:
                                        self._downloaded_files.append(r)
                                        self._log(f"[OK] Downloaded {report['name']}: {r.name}")
                                elif results:
                                    self._downloaded_files.append(results)
                                    self._log(f"[OK] Downloaded {report['name']}: {results.name}")
                            except Exception as exc:
                                self._log(f"[ERROR] Failed to download {report['name']}: {exc}")
                                if mode == "download":
                                    return
                    finally:
                        close_session(context, pw)

                except Exception as exc:
                    self._log(f"[ERROR] Download failed: {exc}")
                    if mode == "download":
                        return
                    build_errors = self._preflight_build_inputs(cfg)
                    if build_errors:
                        for error in build_errors:
                            self._log(f"[ERROR] {error}")
                        self._log("[ERROR] Build step skipped because required inputs are missing.")
                        return
                    self._log("[WARN] Download failed, but required local CSVs already exist. Continuing with build.")

            if mode in ("all", "build"):
                step = "2/2" if mode == "all" else "1/1"
                build_errors = self._preflight_build_inputs(cfg)
                if build_errors:
                    for error in build_errors:
                        self._log(f"[ERROR] {error}")
                    self._log("[ERROR] Build preflight failed.")
                    return
                self._log(f"[{step}] Building Ryan report...")

                dl_dir = cfg.get("downloads", {}).get("directory", "")
                if not dl_dir:
                    dl_dir = str(Path.home() / "Downloads" / "ryan-moves-and-tests")
                # Check for xlsx first, then csv
                historical = cfg.get("historical_ryan", "")
                if not historical:
                    for ext in (".xlsx", ".csv"):
                        candidate = Path(dl_dir) / f"2026 RYAN MOVES{ext}"
                        if candidate.exists():
                            historical = str(candidate)
                            break
                    if not historical:
                        historical = str(Path(dl_dir) / "2026 RYAN MOVES.xlsx")
                if historical and not Path(historical).exists():
                    result = self._request_missing_file(historical)
                    if result == "cancel":
                        self._log("[INFO] Build cancelled.")
                        return
                    elif result == "new":
                        self._log("[INFO] Starting fresh -- all orders will be treated as new.")
                        Path(historical).parent.mkdir(parents=True, exist_ok=True)
                        Path(historical).write_text("", encoding="utf-8")
                    else:
                        # User picked a new file path
                        historical = result
                        cfg["historical_ryan"] = historical
                        self.save_config(cfg)
                        self._log(f"[INFO] Updated historical file: {Path(historical).name}")
                fresh_output = str(Path(dl_dir) / "generated-ryan-report-latest-new-only.csv")
                append_output = str(Path(dl_dir) / "append-ryan-report-latest.csv")

                from execution.build_ryan_report import main as build_main
                # State dir must be in user space (app bundle is read-only).
                user_state = str(_ensure_user_state())

                build_args = [
                    "--input-dir", dl_dir,
                    "--output", fresh_output,
                    "--append-to", historical,
                    "--append-output", append_output,
                    "--historical-ryan", historical,
                    "--state-dir", user_state,
                    "--only-new-orders",
                ]
                try:
                    # build_ryan_report.main() uses argparse -- patch sys.argv
                    old_argv = sys.argv
                    sys.argv = ["build_ryan_report"] + build_args
                    try:
                        build_main()
                    finally:
                        sys.argv = old_argv
                    self._log("[OK] Build complete")
                except SystemExit as exc:
                    if exc.code and exc.code != 0:
                        self._log(f"[ERROR] Build failed (exit {exc.code})")
                        return
                except Exception as exc:
                    self._log(f"[ERROR] Build failed: {exc}")
                    return

                # Append new rows to the xlsx file if it exists.
                self._append_to_xlsx(historical, fresh_output)

                # Need-based Distribution-PDF nudge: if this run produced moves
                # with no resolvable job number (bare town in From/To), tell the
                # user to upload a fresh RIC Distribution PDF — that's the data
                # that fills job numbers. Only warns when there's a real gap.
                self._last_run_missing_jobs = self._count_missing_job_numbers(fresh_output)
                if self._last_run_missing_jobs > 0:
                    self._log(
                        f"[WARN] {self._last_run_missing_jobs} move(s) are missing job numbers. "
                        f"Upload the latest RIC Distribution Report PDF in Settings to fill them."
                    )

                # Capture a snapshot of this run into last_run/ so the Report
                # Issue button always has fresh diagnostic data to bundle.
                try:
                    try:
                        from app import feedback as _feedback  # type: ignore
                    except ImportError:
                        import feedback as _feedback  # type: ignore
                    _feedback.snapshot_last_run(
                        downloads_dir=Path(dl_dir),
                        output_files=[Path(fresh_output), Path(append_output)],
                        last_run_dir=_managed_last_run_dir(),
                    )
                except Exception as exc:
                    self._log(f"[WARN] last_run snapshot failed: {exc}")

            self._log("[DONE] Pipeline complete!")

            # Increment hours saved on success.
            self._increment_hours_saved(3.0)

            # Clean up: delete only the source files downloaded in THIS run.
            downloaded = getattr(self, "_downloaded_files", [])
            if downloaded:
                for f in downloaded:
                    try:
                        if f.exists():
                            f.unlink()
                            self._log(f"  Cleaned up: {f.name}")
                    except OSError:
                        pass

            # List output files.
            dl_dir = Path(cfg.get("downloads", {}).get("directory", ""))
            if dl_dir.exists():
                for f in sorted(dl_dir.iterdir()):
                    if f.suffix == ".csv":
                        size_kb = f.stat().st_size / 1024
                        self._log(f"  {f.name} ({size_kb:.0f} KB)")

        except Exception as e:
            self._log(f"[ERROR] {e}")
        finally:
            self._running = False

    # -- Report Management --

    def get_reports(self) -> list[dict]:
        """Return list of configured reports with name and enabled status."""
        cfg = self.load_config()
        reports = cfg.get("reports", [])
        return [{"name": r.get("name", ""), "enabled": r.get("enabled", True)} for r in reports]

    def toggle_report(self, name: str, enabled: bool) -> str:
        """Enable or disable a report by name."""
        cfg = self.load_config()
        for r in cfg.get("reports", []):
            if r.get("name") == name:
                r["enabled"] = enabled
                self.save_config(cfg)
                return "ok"
        return "not found"

    def add_report(self, name: str, menu_path: str) -> str:
        """Add a new report. menu_path is like 'Trucking > Reporter Reports > My Report'."""
        cfg = self.load_config()
        parts = [p.strip() for p in menu_path.split(">")]
        if len(parts) < 2:
            return "Need at least 2 menu items (e.g. 'Trucking > Report Name')"

        steps = [{"action": "click_tab", "name": "Contents", "wait_ms": 1000}]
        # First part is always a tab.
        steps.append({"action": "click_tab", "name": parts[0], "wait_ms": 2000})
        # Middle parts are menu clicks.
        for part in parts[1:-1]:
            steps.append({"action": "click_menu", "text": part, "wait_ms": 3000})
        # Last part is the report itself (also a menu click), then Export.
        steps.append({"action": "click_menu", "text": parts[-1], "wait_ms": 3000})
        steps.append({
            "action": "click_button", "text": "Export",
            "wait_ms": 1000, "triggers_download": True, "timeout_ms": 60000,
        })

        report = {"enabled": True, "name": name, "steps": steps}
        cfg.setdefault("reports", []).append(report)
        self.save_config(cfg)
        return "ok"

    def remove_report(self, name: str) -> str:
        """Remove a report by name."""
        cfg = self.load_config()
        cfg["reports"] = [r for r in cfg.get("reports", []) if r.get("name") != name]
        self.save_config(cfg)
        return "ok"

    def get_report_detail(self, name: str) -> dict | None:
        """Return full report definition including steps."""
        cfg = self.load_config()
        for r in cfg.get("reports", []):
            if r.get("name") == name:
                return r
        return None

    def save_report(self, report: dict) -> str:
        """Save a full report definition (create or update).
        report must have 'name' and 'steps' keys."""
        cfg = self.load_config()
        reports = cfg.get("reports", [])
        name = report.get("name", "")
        if not name:
            return "error: name required"

        # Normalize steps
        for step in report.get("steps", []):
            step.setdefault("action", "click_tab")
            step.setdefault("label", "")
            step.setdefault("wait_ms", 1000)
            step.setdefault("triggers_download", False)
            # Ensure 'name' or 'text' target field exists
            if step["action"] in ("set_end_date_today", "set_report_end_date_today"):
                step["triggers_download"] = False
            elif step["action"] == "click_tab":
                step.setdefault("name", step.get("text", ""))
            else:
                step.setdefault("text", step.get("name", ""))

        # Update existing or append new
        found = False
        for i, r in enumerate(reports):
            if r.get("name") == name:
                report["enabled"] = r.get("enabled", True)
                report.setdefault("version", r.get("version", 0) + 1)
                reports[i] = report
                found = True
                break
        if not found:
            report.setdefault("enabled", True)
            report.setdefault("version", 1)
            reports.append(report)

        cfg["reports"] = reports
        self.save_config(cfg)
        return "ok"

    def test_run_report(self, name: str) -> str:
        """Test-run a single report path. Runs in background thread."""
        if self._running:
            return "already running"
        self._running = True
        self._log_lines.clear()
        t = threading.Thread(target=self._test_run, args=(name,), daemon=True)
        t.start()
        return "started"

    def _test_run(self, name: str) -> None:
        """Execute a single report path for testing.

        Delegates browser lifecycle (launch/login/cleanup) to
        execution.download_reports.run_single_report so both the CLI and the
        desktop app share one code path.
        """
        try:
            config = self.get_config_path()
            cfg = self.load_config()

            report = None
            for r in cfg.get("reports", []):
                if r.get("name") == name:
                    report = r
                    break
            if not report:
                self._log(f"[ERROR] Report '{name}' not found.")
                return

            validation = self.validate_config()
            for warning in validation["warnings"]:
                self._log(f"[WARN] {warning}")
            if validation["errors"]:
                for error in validation["errors"]:
                    self._log(f"[ERROR] {error}")
                return

            sys.path.insert(0, str(EXECUTION.parent))
            from execution.download_reports import (
                load_config as dl_load_config,
                run_single_report,
            )

            self._log(f"[INFO] Test-running report: {name}")
            dl_cfg = dl_load_config(Path(config))

            result = run_single_report(dl_cfg, report, log=self._log)
            if isinstance(result, list):
                if result:
                    for r in result:
                        self._log(f"[OK] Test download succeeded: {r.name}")
                else:
                    self._log("[OK] Test run completed (no download expected)")
            elif result:
                self._log(f"[OK] Test download succeeded: {result.name}")
            else:
                self._log("[OK] Test run completed (no download expected)")

            self._log("[DONE] Test run complete!")
        except Exception as e:
            self._log(f"[ERROR] Test run failed: {e}")
        finally:
            self._running = False

    # -- Output info --

    def get_output_files(self) -> list[dict]:
        cfg = self.load_config()
        dl_dir = Path(cfg.get("downloads", {}).get("directory", ""))
        files = []
        if dl_dir.exists():
            for f in sorted(dl_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.suffix == ".csv":
                    st = f.stat()
                    files.append({
                        "name": f.name,
                        "path": str(f),
                        "size_kb": round(st.st_size / 1024, 1),
                        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                    })
        return files

    def get_unresolved_serials(self) -> list[dict]:
        p = _user_state_dir() / "unresolved_serials.csv"
        if not p.exists():
            p = STATE / "unresolved_serials.csv"
        if not p.exists():
            return []
        import csv
        with p.open("r") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader][:50]  # cap at 50

    def open_folder(self, path: str) -> None:
        import subprocess
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    def open_report(self) -> str:
        """Open the updated report workbook file (the historical Ryan xlsx that
        the build appends to). Falls back to its containing folder if the file
        path is unset or missing. Returns a short status string for the UI."""
        cfg = self.load_config()
        report = Path(cfg.get("historical_ryan", "") or "")
        if report and report.exists():
            self.open_folder(str(report))
            return "opened"
        # No usable file path -- open the containing folder if we have one,
        # otherwise the managed downloads dir, so the user can find the report.
        target = report.parent if str(report) else Path(cfg.get("downloads", {}).get("directory", ""))
        if target and target.exists():
            self.open_folder(str(target))
            return "opened_folder"
        return "not_found"

    # -- Scheduling --

    def _plist_path(self) -> Path:
        return Path.home() / "Library/LaunchAgents/com.andrewnaegele.catom.plist"

    def _task_name(self) -> str:
        return "CatomReportSchedule"

    def get_schedule(self) -> dict[str, Any]:
        """Return the current schedule config, or empty if none."""
        cfg = self.load_config()
        return cfg.get("schedule", {})

    def set_schedule(self, enabled: bool, day: str, hour: int, minute: int) -> str:
        """Set or remove the scheduled run. day: 'daily' or 'monday'-'sunday'."""
        cfg = self.load_config()
        cfg["schedule"] = {
            "enabled": enabled,
            "day": day,
            "hour": hour,
            "minute": minute,
        }
        self.save_config(cfg)

        if not enabled:
            self._remove_schedule()
            return "Schedule removed"

        if sys.platform == "darwin":
            return self._set_launchd_schedule(day, hour, minute)
        elif sys.platform == "win32":
            return self._set_windows_schedule(day, hour, minute)
        return "Scheduling not supported on this platform"

    def _set_launchd_schedule(self, day: str, hour: int, minute: int) -> str:
        import plistlib
        import subprocess

        config = self.get_config_path()
        # In frozen app, launch the app binary; in dev, use python + script.
        if getattr(sys, "frozen", False):
            program_args = ["/Applications/Catom.app/Contents/MacOS/Catom", "--run-scheduled"]
        else:
            program_args = [sys.executable, str(EXECUTION / "run_pipeline.py"), "--config", config]

        # Build the calendar interval.
        cal: dict[str, int] = {"Hour": hour, "Minute": minute}
        day_map = {
            "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
            "thursday": 4, "friday": 5, "saturday": 6,
        }
        if day.lower() in day_map:
            cal["Weekday"] = day_map[day.lower()]

        plist = {
            "Label": "com.andrewnaegele.catom",
            "ProgramArguments": program_args,
            "StartCalendarInterval": cal,
            "WorkingDirectory": str(APP_ROOT),
            "StandardOutPath": str(Path.home() / "Library/Logs/catom-report.log"),
            "StandardErrorPath": str(Path.home() / "Library/Logs/catom-report.log"),
            "RunAtLoad": False,
        }

        plist_path = self._plist_path()
        # Unload existing if present.
        subprocess.run(["launchctl", "unload", str(plist_path)],
                       capture_output=True, check=False)

        with plist_path.open("wb") as f:
            plistlib.dump(plist, f)

        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        return f"Scheduled: {day} at {hour:02d}:{minute:02d}"

    def _set_windows_schedule(self, day: str, hour: int, minute: int) -> str:
        import subprocess

        config = self.get_config_path()
        if getattr(sys, "frozen", False):
            program = f'"{sys.executable}" "--run-scheduled"'
        else:
            program = f'"{sys.executable}" "{EXECUTION / "run_pipeline.py"}" "--config" "{config}"'
        task = self._task_name()
        time_str = f"{hour:02d}:{minute:02d}"

        # Delete existing task if present.
        subprocess.run(["schtasks", "/delete", "/tn", task, "/f"],
                       capture_output=True, check=False)

        if day.lower() == "daily":
            day_arg = "daily"
        else:
            day_arg = "weekly"

        cmd = [
            "schtasks", "/create", "/tn", task,
            "/tr", program,
            "/sc", day_arg,
            "/st", time_str,
        ]
        if day.lower() != "daily":
            cmd.extend(["/d", day[:3].upper()])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return f"Failed to create schedule: {result.stderr}"
        return f"Scheduled: {day} at {time_str}"

    def _remove_schedule(self) -> None:
        import subprocess
        if sys.platform == "darwin":
            plist_path = self._plist_path()
            subprocess.run(["launchctl", "unload", str(plist_path)],
                           capture_output=True, check=False)
            plist_path.unlink(missing_ok=True)
        elif sys.platform == "win32":
            subprocess.run(["schtasks", "/delete", "/tn", self._task_name(), "/f"],
                           capture_output=True, check=False)

    # -- AI Troubleshooting --

    def troubleshoot(self, error_log: str) -> str:
        """Send error logs to Claude API for troubleshooting advice."""
        try:
            import urllib.request
            import urllib.error

            # Look for API key in config or environment.
            cfg = self.load_config()
            api_key = cfg.get("anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                return (
                    "No API key configured. To enable AI troubleshooting:\n\n"
                    "1. Go to Settings\n"
                    "2. Add your Anthropic API key\n"
                    "3. Try again\n\n"
                    "Common fixes:\n"
                    "- 'Login failed' error: Check your Axon username/password in Settings\n"
                    "- 'element not found' error: The Axon page layout may have changed -- contact support\n"
                    "- 'Download failed' error: Try running the report again, or check Axon is reachable\n"
                    "- 'FileNotFoundError': Check that your Ryan Moves CSV path is correct in Settings"
                )

            prompt = (
                "You are a troubleshooting assistant for the Ryan Report app. "
                "This app downloads reports from Axon TMS (a trucking management system) "
                "via browser automation using its own bundled Chromium and builds a combined CSV report. "
                "The user got an error. Diagnose the problem and give a clear, "
                "non-technical fix in 2-3 sentences. Here's the error log:\n\n"
                f"{error_log[-2000:]}"
            )

            body = json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )

            with updater._urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                return result["content"][0]["text"]

        except urllib.error.HTTPError as e:
            return f"API error ({e.code}): Check that your API key is valid."
        except Exception as e:
            return f"Could not reach Claude: {e}\n\nCheck your internet connection and try again."


# ---------------------------------------------------------------------------
# WebView2 runtime detection (Windows). See main()'s preflight for why a
# missing runtime is fatal rather than a silent MSHTML fallback.
# ---------------------------------------------------------------------------

def _webview2_runtime_present() -> bool:
    """True if the Edge WebView2 Evergreen Runtime is installed.

    The runtime registers its version under a well-known registry key (both
    per-machine and per-user installs). We check both. If the key is missing
    or empty, WebView2 isn't usable and the HTML UI would be dead.

    Errors are treated as 'present' (return True) so we never block launch over
    a detection quirk — the pinned gui='edgechromium' backend will still raise
    loudly at webview.start() if the runtime is truly unusable.
    """
    if platform.system() != "Windows":
        return True
    try:
        import winreg  # type: ignore
    except Exception:
        return True

    key_path = (
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
        r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    hives = (
        (winreg.HKEY_LOCAL_MACHINE, key_path),
        (winreg.HKEY_CURRENT_USER, key_path),
        # 64-bit view (no WOW6432Node) for completeness.
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
         r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    )
    for hive, path in hives:
        try:
            with winreg.OpenKey(hive, path) as k:
                version, _ = winreg.QueryValueEx(k, "pv")
                if version and str(version) not in ("", "0.0.0.0"):
                    return True
        except FileNotFoundError:
            continue
        except Exception:
            # Unexpected error reading the registry — don't block launch.
            return True
    return False


def _show_native_error(title: str, message: str) -> None:
    """Best-effort native message box so a fatal startup problem is visible
    even when the HTML UI can't load. Windows only; no-op elsewhere."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_ICONERROR)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App entry point.
# ---------------------------------------------------------------------------

def main() -> None:
    _install_excepthook()
    _file_log(f"=== Catom starting (frozen={getattr(sys, 'frozen', False)}, "
              f"platform={platform.system()}, argv={sys.argv}) ===")

    # --run-scheduled: headless mode for cron/launchd/Task Scheduler.
    if "--run-scheduled" in sys.argv:
        api = PipelineAPI()
        api._run("all")
        sys.exit(0)

    # WebView2 preflight (Windows). The UI is an HTML page whose buttons are
    # wired with ES2017 `async` handlers (runPipeline, init). pywebview renders
    # it through the EdgeChromium (WebView2) backend. If the WebView2 runtime is
    # missing, pywebview SILENTLY falls back to MSHTML (legacy IE11/Trident),
    # which cannot parse `async function` at all — so the ENTIRE <script> fails,
    # `window.pywebview.api` is never wired, and every button (including Run
    # Report) does nothing, with no error reaching catom.log. That is the
    # "click Run, nothing happens, zero pipeline log lines" symptom: the Python
    # side keeps running (the launch update check still logs) while the JS UI is
    # inert. We refuse to launch into that silent-dead state.
    if platform.system() == "Windows" and not _webview2_runtime_present():
        _file_log(
            "[FATAL] WebView2 runtime not found. Catom's UI cannot start and "
            "every button would be dead. Install the Microsoft Edge WebView2 "
            "Evergreen Runtime, then relaunch Catom. "
            "https://developer.microsoft.com/microsoft-edge/webview2/"
        )
        _show_native_error(
            "Catom can't start",
            "Catom needs the Microsoft Edge WebView2 Runtime, which isn't "
            "installed on this PC (or was removed/blocked by IT).\n\n"
            "Without it the window opens but the buttons don't respond.\n\n"
            "Fix: install 'Microsoft Edge WebView2 Runtime' (Evergreen), then "
            "open Catom again. Ask IT if downloads are blocked.",
        )
        _file_log("=== Catom exiting (WebView2 missing) ===")
        sys.exit(1)

    api = PipelineAPI()
    window = webview.create_window(
        "Catom",
        _ui_path(),
        js_api=api,
        width=800,
        height=620,
        resizable=True,
        min_size=(600, 400),
    )
    api.set_window(window)

    # Fire the auto-update check on a background thread once the UI is loaded.
    # We register this as a pywebview start callback so the window exists before
    # we try to call evaluate_js from the worker. Windows-only — Mac builds
    # silently skip (no .msi/.exe upgrade path on macOS yet).
    def _post_load_hooks() -> None:
        if platform.system() == "Windows":
            api._start_background_update_check()

    try:
        # gui='edgechromium' on Windows: pin the modern backend so pywebview
        # NEVER silently degrades to MSHTML. With this set, a missing/broken
        # WebView2 raises here (logged below + caught by the preflight above)
        # instead of rendering a UI whose async JS can't run.
        start_kwargs: dict[str, Any] = {"debug": ("--debug" in sys.argv)}
        if platform.system() == "Windows":
            start_kwargs["gui"] = "edgechromium"
        webview.start(_post_load_hooks, **start_kwargs)
    except Exception:
        _file_log(f"webview.start raised:\n{traceback.format_exc()}")
        raise
    _file_log("=== Catom exiting cleanly ===")


if __name__ == "__main__":
    main()
