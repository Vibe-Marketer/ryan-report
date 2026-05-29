"""Auto-update for Catom (Windows).

Flow:
  1. App polls `https://updates.aisimple.co/catom/latest.json` on launch (async).
  2. If a newer version exists, UI shows an "Update Available" banner.
  3. User clicks "Update Now" -> we download the new NSIS installer to %TEMP%.
  4. We launch it with `/S` (silent install) and exit the current app.
  5. NSIS uninstalls the old version, installs the new one, and (per the .nsi
     finish-action) relaunches Catom into the new version.

Eric never sees GitHub or any underlying infrastructure — just the banner.

Network failures are swallowed silently. We never crash the app over an
update check. The user can still run the app on an old version forever if
the update server is down.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

try:
    from app.__version__ import __version__
except ImportError:
    # When frozen by PyInstaller, the entry script imports differently.
    from __version__ import __version__  # type: ignore


UPDATE_FEED_URL = "https://updates.aisimple.co/catom/latest.json"
CHECK_TIMEOUT_SECS = 8
DOWNLOAD_TIMEOUT_SECS = 600  # 10 min — installer is ~200MB on a slow connection
USER_AGENT = f"Catom/{__version__}"


def _parse_version(v: str) -> tuple[int, ...]:
    """'1.2.3' / 'v1.2.3' -> (1, 2, 3). Non-numeric segments are dropped."""
    cleaned = v.lstrip("vV").strip()
    parts = []
    for piece in cleaned.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts) or (0,)


def check_for_update() -> dict | None:
    """Return {'version', 'url', 'notes'} if a newer version exists, else None.

    Synchronous network call. Use `check_async` to avoid blocking the UI thread.
    """
    try:
        req = urllib.request.Request(
            UPDATE_FEED_URL,
            headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT_SECS) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None

    latest = str(data.get("version", "")).strip()
    url = str(data.get("url", "")).strip()
    if not latest or not url:
        return None
    if _parse_version(latest) <= _parse_version(__version__):
        return None
    return {
        "version": latest,
        "url": url,
        "notes": str(data.get("notes", "")).strip(),
    }


def check_async(on_available: Callable[[dict], None]) -> None:
    """Fire-and-forget update check. Calls on_available({...}) only if update exists."""

    def _worker():
        result = check_for_update()
        if result:
            try:
                on_available(result)
            except Exception:
                # Never let UI callback crash the worker.
                pass

    threading.Thread(target=_worker, daemon=True).start()


def download_installer(
    url: str,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download the installer to %TEMP%\\Catom-Update.exe and return its path.

    on_progress is called with (bytes_downloaded, total_bytes). total may be 0
    if Content-Length is missing.
    """
    dest = Path(tempfile.gettempdir()) / "Catom-Update.exe"
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            pass

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECS) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with dest.open("wb") as fh:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    try:
                        on_progress(downloaded, total)
                    except Exception:
                        pass
    return dest


def apply_and_exit(installer_path: Path) -> None:
    """Launch the new installer silently and exit this process.

    Windows-only. NSIS `/S` flag runs the installer with no UI; the .nsi's
    onFinish block relaunches Catom into the new version.
    """
    if sys.platform != "win32":
        raise RuntimeError("Auto-update is Windows-only.")

    if not installer_path.exists():
        raise FileNotFoundError(f"Installer not found at {installer_path}")

    # DETACHED_PROCESS = 0x00000008 -- the installer runs independent of our
    # process so we can exit cleanly without killing it.
    DETACHED_PROCESS = 0x00000008

    subprocess.Popen(
        [str(installer_path), "/S"],
        creationflags=DETACHED_PROCESS,
        close_fds=True,
    )

    # Exit hard so the installer can replace our binaries without
    # file-in-use locks. os._exit skips Python finalizers; that's deliberate.
    os._exit(0)


# ---------------------------------------------------------------------------
# Public surface for the pywebview UI -- these are wrapped by PipelineAPI in
# main.py so the JS layer can call window.pywebview.api.update_*.
# ---------------------------------------------------------------------------


_PENDING_INSTALLER: Path | None = None


def ui_check_for_update() -> dict | None:
    """Synchronous check -- returns the update dict or None."""
    return check_for_update()


def ui_download_update(url: str) -> dict:
    """Download the installer. Returns {'ok': bool, 'path': str, 'error': str}."""
    global _PENDING_INSTALLER
    try:
        path = download_installer(url)
        _PENDING_INSTALLER = path
        return {"ok": True, "path": str(path), "error": ""}
    except Exception as exc:
        return {"ok": False, "path": "", "error": str(exc)}


def ui_apply_update() -> dict:
    """Launch the downloaded installer + exit. Only returns on failure."""
    global _PENDING_INSTALLER
    if _PENDING_INSTALLER is None or not _PENDING_INSTALLER.exists():
        return {"ok": False, "error": "No installer downloaded yet."}
    try:
        apply_and_exit(_PENDING_INSTALLER)
        # apply_and_exit never returns; this is defensive.
        return {"ok": True, "error": ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
