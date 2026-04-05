"""Ryan Report — Desktop App

A simple desktop UI for running the Ryan report pipeline.
Double-click to launch, click a button to run.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import webview


# ---------------------------------------------------------------------------
# Path resolution — works both in dev and when frozen by PyInstaller.
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


# ---------------------------------------------------------------------------
# Pipeline API — exposed to the webview JS layer.
# ---------------------------------------------------------------------------

class PipelineAPI:
    """Methods callable from the browser UI via window.pywebview.api.*"""

    def __init__(self, window: webview.Window | None = None):
        self._window = window
        self._running = False
        self._log_lines: list[str] = []

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    # -- Config helpers --

    def get_config_path(self) -> str:
        p = EXECUTION / "browser_config.json"
        if p.exists():
            return str(p)
        ex = EXECUTION / "browser_config.example.json"
        return str(ex) if ex.exists() else ""

    def load_config(self) -> dict[str, Any]:
        p = Path(self.get_config_path())
        if not p.exists():
            return {}
        with p.open("r") as f:
            cfg = json.load(f)
        # Expand ${HOME} etc.
        def _exp(o: Any) -> Any:
            if isinstance(o, str):
                return os.path.expandvars(o)
            if isinstance(o, dict):
                return {k: _exp(v) for k, v in o.items()}
            if isinstance(o, list):
                return [_exp(v) for v in o]
            return o
        return _exp(cfg)

    def save_config(self, cfg: dict) -> str:
        p = EXECUTION / "browser_config.json"
        with p.open("w") as f:
            json.dump(cfg, f, indent=2)
        return "ok"

    # -- Auto-detection --

    def is_configured(self) -> bool:
        """Return True if a valid config exists with credentials filled in."""
        cfg = self.load_config()
        return bool(cfg.get("auth", {}).get("username"))

    def detect_browsers(self) -> list[dict[str, str]]:
        """Scan for installed Chromium-based browsers. Returns list of
        {name, path, user_data_dir} for each found browser."""
        import platform as plat

        browsers: list[dict[str, str]] = []
        is_mac = plat.system() == "Darwin"
        is_win = plat.system() == "Windows"
        home = Path.home()

        candidates: list[tuple[str, str, str]] = []
        if is_mac:
            candidates = [
                ("Google Chrome",
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 str(home / "Library/Application Support/Google/Chrome")),
                ("Brave Browser",
                 "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                 str(home / "Library/Application Support/BraveSoftware/Brave-Browser")),
                ("Microsoft Edge",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 str(home / "Library/Application Support/Microsoft Edge")),
                ("Comet",
                 "/Applications/Comet.app/Contents/MacOS/Comet",
                 str(home / "Library/Application Support/Comet")),
                ("Chromium",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 str(home / "Library/Application Support/Chromium")),
            ]
        elif is_win:
            localappdata = os.environ.get("LOCALAPPDATA", "")
            programfiles = os.environ.get("PROGRAMFILES", "C:\\Program Files")
            programfiles86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
            candidates = [
                ("Google Chrome",
                 f"{programfiles}\\Google\\Chrome\\Application\\chrome.exe",
                 f"{localappdata}\\Google\\Chrome\\User Data"),
                ("Google Chrome (x86)",
                 f"{programfiles86}\\Google\\Chrome\\Application\\chrome.exe",
                 f"{localappdata}\\Google\\Chrome\\User Data"),
                ("Brave Browser",
                 f"{programfiles}\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
                 f"{localappdata}\\BraveSoftware\\Brave-Browser\\User Data"),
                ("Microsoft Edge",
                 f"{programfiles86}\\Microsoft\\Edge\\Application\\msedge.exe",
                 f"{localappdata}\\Microsoft\\Edge\\User Data"),
            ]

        for name, exe, user_data in candidates:
            if Path(exe).exists():
                browsers.append({
                    "name": name,
                    "path": exe,
                    "user_data_dir": user_data,
                })

        return browsers

    def detect_profiles(self, user_data_dir: str) -> list[str]:
        """List available Chrome profile directories."""
        ud = Path(user_data_dir)
        if not ud.exists():
            return ["Default"]
        profiles = []
        if (ud / "Default").exists():
            profiles.append("Default")
        for p in sorted(ud.iterdir()):
            if p.is_dir() and p.name.startswith("Profile "):
                profiles.append(p.name)
        return profiles if profiles else ["Default"]

    def get_default_download_dir(self) -> str:
        return str(Path.home() / "Downloads" / "ryan-moves-and-tests")

    # -- File browser --

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
            file_types=("CSV Files (*.csv)", "All Files (*.*)"),
        )
        if result and len(result) > 0:
            return result[0]
        return None

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

    def _run(self, mode: str) -> None:
        import subprocess

        try:
            python = sys.executable
            config = self.get_config_path()

            if mode in ("all", "download"):
                self._log("[1/2] Downloading reports from Axon...")
                result = subprocess.run(
                    [python, str(EXECUTION / "download_reports.py"), "--config", config],
                    capture_output=True, text=True, timeout=300,
                )
                for line in (result.stdout + result.stderr).strip().splitlines():
                    self._log(line)
                if result.returncode != 0:
                    self._log(f"[ERROR] Download failed (exit {result.returncode})")
                    if mode == "download":
                        return

            if mode in ("all", "build"):
                step = "2/2" if mode == "all" else "1/1"
                self._log(f"[{step}] Building Ryan report...")
                cmd = [python, str(EXECUTION / "run_pipeline.py"), "--config", config, "--skip-download"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                for line in (result.stdout + result.stderr).strip().splitlines():
                    self._log(line)
                if result.returncode != 0:
                    self._log(f"[ERROR] Build failed (exit {result.returncode})")
                    return

            self._log("[DONE] Pipeline complete!")

            # List output files.
            cfg = self.load_config()
            dl_dir = Path(cfg.get("downloads", {}).get("directory", ""))
            if dl_dir.exists():
                for f in sorted(dl_dir.iterdir()):
                    if f.suffix == ".csv":
                        size_kb = f.stat().st_size / 1024
                        self._log(f"  {f.name} ({size_kb:.0f} KB)")

            # Push to Airtable if configured.
            airtable = cfg.get("airtable", {})
            if airtable.get("enabled") and airtable.get("token") and airtable.get("table_url"):
                self._push_to_airtable(cfg)

        except subprocess.TimeoutExpired:
            self._log("[ERROR] Pipeline timed out after 5 minutes")
        except Exception as e:
            self._log(f"[ERROR] {e}")
        finally:
            self._running = False

    # -- Airtable --

    def _parse_airtable_url(self, url: str) -> tuple[str, str]:
        """Extract base ID and table name/ID from an Airtable URL.
        Handles: https://airtable.com/appXXXXX/tblYYYYY/...
        """
        import re
        m = re.search(r"airtable\.com/(app\w+)/(tbl\w+)", url)
        if m:
            return m.group(1), m.group(2)
        # Try simpler format: just base/table IDs pasted directly.
        parts = url.strip().strip("/").split("/")
        base = next((p for p in parts if p.startswith("app")), "")
        table = next((p for p in parts if p.startswith("tbl")), "")
        return base, table

    def _push_to_airtable(self, cfg: dict) -> None:
        """Push the latest generated report rows to Airtable."""
        import csv as csv_mod
        import urllib.request
        import urllib.error

        airtable = cfg.get("airtable", {})
        token = airtable.get("token", "")
        base_id, table_id = self._parse_airtable_url(airtable.get("table_url", ""))

        if not (token and base_id and table_id):
            self._log("[WARN] Airtable not fully configured — skipping push")
            return

        # Read the generated report CSV.
        dl_dir = Path(cfg.get("downloads", {}).get("directory", ""))
        report_csv = dl_dir / "generated-ryan-report-latest-new-only.csv"
        if not report_csv.exists():
            self._log("[WARN] No generated report found — skipping Airtable push")
            return

        # Parse CSV — skip the two header rows, read data rows.
        with report_csv.open("r", encoding="utf-8-sig") as f:
            lines = list(csv_mod.reader(f))

        if len(lines) < 3:
            self._log("[INFO] No data rows to push to Airtable")
            return

        # Column names from the output (row index -> field name).
        field_names = ["Row", "Truck#", "PO#", "By Whom", "Date Move",
                       "Machine#", "Hour Meter", "Machine Description",
                       "From", "To", "Order#"]

        # Which columns to push (configurable, defaults to all).
        selected = airtable.get("columns", field_names)

        records = []
        for row in lines[2:]:  # Skip 2 header rows.
            if not row or not any(row):
                continue
            fields = {}
            for i, name in enumerate(field_names):
                if i < len(row) and name in selected:
                    val = row[i].strip()
                    if val:
                        fields[name] = val
            if fields:
                records.append({"fields": fields})

        if not records:
            self._log("[INFO] No records to push to Airtable")
            return

        self._log(f"[INFO] Pushing {len(records)} rows to Airtable...")

        # Airtable API allows max 10 records per request.
        url = f"https://api.airtable.com/v0/{base_id}/{table_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        pushed = 0
        for i in range(0, len(records), 10):
            batch = records[i:i+10]
            body = json.dumps({"records": batch}).encode()
            req = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    pushed += len(batch)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode()[:200]
                self._log(f"[ERROR] Airtable API error ({e.code}): {err_body}")
                return
            except Exception as e:
                self._log(f"[ERROR] Airtable push failed: {e}")
                return

        self._log(f"[OK] Pushed {pushed} rows to Airtable")

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
        import subprocess

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

        python = sys.executable
        config = self.get_config_path()
        script = str(EXECUTION / "run_pipeline.py")

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
            "ProgramArguments": [python, script, "--config", config],
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

        python = sys.executable
        config = self.get_config_path()
        script = str(EXECUTION / "run_pipeline.py")
        task = self._task_name()
        time_str = f"{hour:02d}:{minute:02d}"

        # Delete existing task if present.
        subprocess.run(["schtasks", "/delete", "/tn", task, "/f"],
                       capture_output=True, check=False)

        if day.lower() == "daily":
            schedule_type, day_arg = "/sc", "daily"
        else:
            schedule_type = "/sc"
            day_arg = "weekly"

        cmd = [
            "schtasks", "/create", "/tn", task,
            "/tr", f'"{python}" "{script}" "--config" "{config}"',
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
                    "- 'Profile lock' error: Close your browser, reopen it, try again\n"
                    "- 'element not found' error: The Axon page layout may have changed — contact support\n"
                    "- 'Download failed' error: Make sure you're logged into Axon in your browser\n"
                    "- 'FileNotFoundError': Check that your Ryan Moves CSV path is correct in Settings"
                )

            prompt = (
                "You are a troubleshooting assistant for the Ryan Report app. "
                "This app downloads reports from Axon TMS (a trucking management system) "
                "via browser automation (Playwright CDP) and builds a combined CSV report. "
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

            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                return result["content"][0]["text"]

        except urllib.error.HTTPError as e:
            return f"API error ({e.code}): Check that your API key is valid."
        except Exception as e:
            return f"Could not reach Claude: {e}\n\nCheck your internet connection and try again."


# ---------------------------------------------------------------------------
# App entry point.
# ---------------------------------------------------------------------------

def main() -> None:
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
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
