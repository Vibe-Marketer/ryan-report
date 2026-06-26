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
import ssl
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


def ssl_context() -> ssl.SSLContext:
    """A TLS context that always has a CA trust store, even when frozen.

    Why this exists:
      In a PyInstaller --onedir build on Windows, the embedded Python has NO
      system CA bundle on `ssl`'s default search path. `urllib.request.urlopen`
      then fails TLS verification with SSLCertVerificationError, which urllib
      re-raises as `urllib.error.URLError`. That is the exact
      `[UPDATE] check failed (...): URLError` the client hit on every launch —
      while the SAME feed verified fine from the dev machine (which has certifi
      / a system CA store on its path).

      We pin the context to certifi's CA bundle. `certifi` is a pure-data wheel;
      we add it to requirements + bundle it via PyInstaller --collect-data so
      `certifi.where()` resolves inside the frozen app. If certifi somehow isn't
      present, we fall back to the platform default context rather than crash —
      the network call may still fail, but the app keeps running.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _urlopen(req: "urllib.request.Request | str", timeout: float):
    """urlopen that always passes our certifi-backed SSL context for https.

    Use this everywhere instead of bare urllib.request.urlopen so no network
    path in the frozen build is left relying on the (missing) system CA store.
    """
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


def _ulog(msg: str) -> None:
    """Append an update-check line to the same catom.log main.py writes, so we
    have hard evidence each check ran (and what it found) without a UI."""
    try:
        import datetime
        import os
        import platform
        home = os.path.expanduser("~")
        if platform.system() == "Windows":
            base = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
            log = os.path.join(base, "Catom", "catom.log")
        elif platform.system() == "Darwin":
            log = os.path.join(home, "Library", "Application Support", "Catom", "catom.log")
        else:
            log = os.path.join(home, ".config", "catom", "catom.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] [UPDATE] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# R2 signed-URL path. Some client networks (e.g. corporate content filters)
# block the custom domain `updates.aisimple.co` by name, so the public feed at
# UPDATE_FEED_URL never loads and the client is stuck on its installed version.
# The raw R2 endpoint (`*.r2.cloudflarestorage.com`) is a recognized
# cloud-storage host those filters allow -- it's the SAME host the feedback
# uploader already reaches successfully. So we fetch the feed + installer via
# short-lived SigV4 presigned URLs on that host, reusing the baked R2
# credentials. generate_presigned_url is pure local signing (no network), so it
# can't fail with URLError; the actual GET still goes through _urlopen + certifi.
# Falls back to the public custom-domain URL when no R2 creds are baked (dev).
# ---------------------------------------------------------------------------

def _r2_config():
    """(endpoint, access_key, secret_key, bucket) from baked creds/env, or None."""
    import os
    try:
        from app import feedback_credentials as _c  # type: ignore
    except ImportError:
        try:
            import feedback_credentials as _c  # type: ignore
        except ImportError:
            _c = None
    ak = (getattr(_c, "R2_ACCESS_KEY_ID", "") if _c else "") or os.environ.get("R2_ACCESS_KEY_ID", "")
    sk = (getattr(_c, "R2_SECRET_ACCESS_KEY", "") if _c else "") or os.environ.get("R2_SECRET_ACCESS_KEY", "")
    ep = (getattr(_c, "R2_ENDPOINT_URL", "") if _c else "") or os.environ.get("R2_ENDPOINT_URL", "")
    bk = (getattr(_c, "R2_BUCKET", "") if _c else "") or os.environ.get("R2_BUCKET", "catom-updates")
    if ak and sk and ep and bk:
        return ep, ak, sk, bk
    return None


def _r2_signed_url(key: str, expires: int = 600) -> str | None:
    """Presign a GET for `key` in the updates bucket on the raw R2 host."""
    cfg = _r2_config()
    if not cfg:
        return None
    endpoint, ak, sk, bucket = cfg
    try:
        import boto3
        from botocore.client import Config as _BotoConfig

        s3 = boto3.client(
            "s3", endpoint_url=endpoint,
            aws_access_key_id=ak, aws_secret_access_key=sk,
            config=_BotoConfig(signature_version="s3v4"), region_name="auto",
        )
        return s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires,
        )
    except Exception:
        return None


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
    # Prefer the R2 host the client's network allows; fall back to the public
    # custom domain. Log which path we used + the real error reason on failure
    # (the bare exception name alone can't tell a cert error from a host block).
    feed_url = _r2_signed_url("catom/latest.json")
    via = "r2" if feed_url else "aisimple"
    if not feed_url:
        feed_url = UPDATE_FEED_URL
    try:
        req = urllib.request.Request(
            feed_url,
            headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
        )
        with _urlopen(req, timeout=CHECK_TIMEOUT_SECS) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        reason = getattr(exc, "reason", "") or str(exc)
        _ulog(f"check failed (running {__version__}, via {via}): {type(exc).__name__}: {reason}")
        return None

    latest = str(data.get("version", "")).strip()
    url = str(data.get("url", "")).strip()
    if not latest or not url:
        _ulog(f"feed missing version/url (running {__version__})")
        return None
    if _parse_version(latest) <= _parse_version(__version__):
        _ulog(f"up to date (running {__version__}, feed {latest}, via {via})")
        return None
    # Download from the same R2 host the feed came through, not the (possibly
    # blocked) aisimple.co url baked into the feed. Construct the installer key
    # from the version and presign it; fall back to the feed's url.
    signed_installer = _r2_signed_url(f"catom/Catom-Setup-v{latest}.exe", expires=900)
    if signed_installer:
        url = signed_installer
    _ulog(f"UPDATE AVAILABLE: {__version__} -> {latest} (via {via})")
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
    with _urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECS) as resp:
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

    # CRITICAL — why this is launched through cmd with a delay, not directly:
    #
    # If we Popen the installer directly, the installer is a CHILD of this Catom
    # process. The installer's first act is `taskkill /F /IM Catom.exe` to free
    # the locked binary — and the old version used `/T` (tree kill), which
    # terminated the installer ITSELF (it's Catom's child). Net result: app
    # closed, installer died with it, nothing installed, version never advanced.
    # That is the "it closed and stayed on the old version" bug.
    #
    # Fix: hand the job to a detached cmd that (1) waits ~3s for THIS process to
    # fully exit, then (2) runs the installer. By then Catom is gone, the
    # installer is parented to that transient cmd (NOT Catom), so nothing kills
    # it. This is the standard self-update launcher pattern on Windows.
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000

    _ulog(f"applying update via {installer_path} (detached, delayed)")

    # ping is a reliable built-in ~3s delay (-n 4 ≈ 3s). The installer path is
    # quoted to survive spaces in %TEMP%.
    launch = f'ping 127.0.0.1 -n 4 >nul & "{installer_path}" /S'
    subprocess.Popen(
        launch,
        shell=True,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        close_fds=True,
    )

    # Exit hard so the installer can replace our binaries without file-in-use
    # locks. os._exit skips Python finalizers; that's deliberate.
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
