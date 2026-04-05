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

        except subprocess.TimeoutExpired:
            self._log("[ERROR] Pipeline timed out after 5 minutes")
        except Exception as e:
            self._log(f"[ERROR] {e}")
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
