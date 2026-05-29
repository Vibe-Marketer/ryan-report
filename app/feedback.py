"""Catom -> Andrew feedback bundle.

When Eric clicks "Report Issue", we zip up everything needed to debug:

  - %APPDATA%\\Catom\\last_run\\*           the input CSVs + output of the most recent run
  - %APPDATA%\\Catom\\catom.log              tail of the app log
  - %APPDATA%\\Catom\\distribution\\*.pdf    the Distribution PDF that was active
  - browser_config.json (with password redacted)
  - feedback.txt                            Eric's typed message + version + timestamp + machine name

Then we upload the zip to R2 at:
  s3://catom-updates/feedback/<YYYY-MM-DD_HHMMSS>-<short-id>.zip

Eric sees: "Sent! Andrew will follow up shortly."
Andrew sees the zip land in his R2 bucket.

R2 credentials are pulled from the same env vars CI uses. In dev they have to be
exported manually; in production the values get baked into the build by the CI
release step OR (preferred) loaded from a packaged-with-the-installer config.
For v1 we accept the inconvenience and ship creds in a build-time constants
file, since the bucket is write-only for the public via these keys (R2 access
keys with no public list, plus the keys never leave the user's machine — they
sit inside the signed installer payload).
"""

from __future__ import annotations

import datetime
import io
import json
import os
import platform
import secrets
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # avoid runtime circular import
    from app.main import PipelineAPI

try:
    from app.__version__ import __version__  # type: ignore
except ImportError:
    from __version__ import __version__  # type: ignore

try:
    from app import feedback_credentials as _creds  # type: ignore
except ImportError:
    try:
        import feedback_credentials as _creds  # type: ignore
    except ImportError:
        _creds = None  # type: ignore


# ---------------------------------------------------------------------------
# R2 credentials -- baked in at build time. See feedback_credentials.py.
# We fall back to env vars so developers can run locally without the constants.
# ---------------------------------------------------------------------------

R2_ACCESS_KEY_ID     = getattr(_creds, "R2_ACCESS_KEY_ID",     "") or os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = getattr(_creds, "R2_SECRET_ACCESS_KEY", "") or os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_ENDPOINT_URL      = getattr(_creds, "R2_ENDPOINT_URL",      "") or os.environ.get("R2_ENDPOINT_URL",      "")
R2_BUCKET            = getattr(_creds, "R2_BUCKET",            "catom-updates")

MAX_BUNDLE_SIZE_BYTES = 75 * 1024 * 1024  # 75 MB cap
LOG_TAIL_LINES        = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redact_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Strip the Axon password before bundling."""
    safe = json.loads(json.dumps(cfg))  # deep copy
    if isinstance(safe.get("auth"), dict) and safe["auth"].get("password"):
        safe["auth"]["password"] = "<redacted>"
    if safe.get("anthropic_api_key"):
        safe["anthropic_api_key"] = "<redacted>"
    return safe


def _tail_log(log_path: Path, n_lines: int = LOG_TAIL_LINES) -> bytes:
    if not log_path.exists():
        return b"(no log file)\n"
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            chunk = min(size, 2 * 1024 * 1024)  # last 2 MB max
            fh.seek(size - chunk)
            tail = fh.read()
        lines = tail.splitlines()[-n_lines:]
        return b"\n".join(lines) + b"\n"
    except OSError as exc:
        return f"(could not read log: {exc})\n".encode()


def _machine_name() -> str:
    try:
        return platform.node() or "unknown"
    except Exception:
        return "unknown"


def _bundle_metadata(message: str) -> bytes:
    info = {
        "version": __version__,
        "timestamp_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "machine": _machine_name(),
        "platform": platform.platform(),
        "user_message": message.strip(),
    }
    return json.dumps(info, indent=2).encode()


# ---------------------------------------------------------------------------
# R2 upload via raw HTTPS + AWS SigV4 (no boto3 dependency — keeps the
# PyInstaller bundle ~30MB smaller).
# ---------------------------------------------------------------------------

def _sigv4_put(
    endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str = "application/zip",
) -> tuple[bool, str]:
    """Minimal S3-compatible PUT with SigV4 signing.

    R2 is S3-compatible. We sign with region 'auto' and service 's3'.
    """
    import hashlib
    import hmac
    from urllib.parse import urlparse, quote

    parsed = urlparse(endpoint)
    host = parsed.netloc
    # Path-style: https://<account>.r2.cloudflarestorage.com/<bucket>/<key>
    path = f"/{bucket}/{quote(key, safe='/')}"
    url = f"{parsed.scheme}://{host}{path}"

    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    region = "auto"
    service = "s3"

    payload_hash = hashlib.sha256(body).hexdigest()

    canonical_uri = path
    canonical_querystring = ""
    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = (
        f"PUT\n{canonical_uri}\n{canonical_querystring}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"{algorithm}\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_date    = _sign(("AWS4" + secret_key).encode(), date_stamp)
    k_region  = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Host", host)
    req.add_header("Content-Type", content_type)
    req.add_header("x-amz-content-sha256", payload_hash)
    req.add_header("x-amz-date", amz_date)
    req.add_header("Authorization", authorization)

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status in (200, 201, 204), f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read()[:300].decode(errors='replace')}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Bundle builder (called from PipelineAPI.send_feedback)
# ---------------------------------------------------------------------------

def build_and_upload_bundle(message: str, api: "PipelineAPI") -> dict[str, Any]:
    """Zip up the diagnostic bundle and ship it to R2. Returns:
        {ok: bool, key: str, size_bytes: int, error: str}
    """
    paths = api.get_managed_paths()
    last_run = Path(paths["last_run"])
    distribution = Path(paths["distribution"])
    log_file = Path(paths["log_file"])
    config_path = Path(api.get_config_path())

    if not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY or not R2_ENDPOINT_URL:
        return {
            "ok": False,
            "key": "",
            "size_bytes": 0,
            "error": "Feedback upload not configured on this build "
                     "(no R2 credentials baked in).",
        }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # metadata
        zf.writestr("feedback.json", _bundle_metadata(message))
        zf.writestr("feedback.txt",
                    f"Catom version: {__version__}\n"
                    f"Machine: {_machine_name()}\n"
                    f"Time: {datetime.datetime.utcnow().isoformat()}Z\n\n"
                    f"User message:\n{message.strip()}\n")
        # redacted config
        try:
            cfg = json.loads(config_path.read_text()) if config_path.exists() else {}
            zf.writestr("browser_config.redacted.json",
                        json.dumps(_redact_config(cfg), indent=2))
        except Exception as exc:
            zf.writestr("browser_config.error.txt", f"Could not read config: {exc}\n")
        # last_run dump
        if last_run.exists():
            for p in sorted(last_run.rglob("*")):
                if p.is_file():
                    rel = "last_run/" + str(p.relative_to(last_run))
                    try:
                        zf.write(p, rel)
                    except OSError as exc:
                        zf.writestr(rel + ".error", f"{exc}\n".encode())
        else:
            zf.writestr("last_run/EMPTY.txt", b"No prior run captured.\n")
        # current distribution PDF
        if distribution.exists():
            for p in sorted(distribution.glob("*.pdf")):
                rel = "distribution/" + p.name
                try:
                    zf.write(p, rel)
                except OSError as exc:
                    zf.writestr(rel + ".error", f"{exc}\n".encode())
        # log tail
        zf.writestr("catom.log.tail", _tail_log(log_file))

    body = buf.getvalue()
    if len(body) > MAX_BUNDLE_SIZE_BYTES:
        return {"ok": False, "key": "", "size_bytes": len(body),
                "error": f"Bundle too large ({len(body)//1024//1024} MB > 75 MB cap)."}

    short_id = secrets.token_hex(3)
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    safe_machine = "".join(c if c.isalnum() or c == "-" else "_" for c in _machine_name())[:24]
    key = f"feedback/{ts}_{safe_machine}_{short_id}.zip"

    ok, msg = _sigv4_put(
        endpoint=R2_ENDPOINT_URL,
        access_key=R2_ACCESS_KEY_ID,
        secret_key=R2_SECRET_ACCESS_KEY,
        bucket=R2_BUCKET,
        key=key,
        body=body,
    )
    if not ok:
        return {"ok": False, "key": key, "size_bytes": len(body),
                "error": f"Upload failed: {msg}"}
    return {"ok": True, "key": key, "size_bytes": len(body), "error": ""}


# ---------------------------------------------------------------------------
# Run capture helper -- the pipeline calls this after each run so the most
# recent inputs+outputs are always sitting in last_run/ for the feedback bundle.
# ---------------------------------------------------------------------------

def snapshot_last_run(downloads_dir: Path, output_files: list[Path], last_run_dir: Path) -> None:
    """Copy the inputs the pipeline used + outputs it produced into last_run/.

    Called from PipelineAPI._run after a successful (or failed) pipeline so the
    feedback button always has fresh diagnostic data to bundle.
    """
    # Wipe and rebuild
    if last_run_dir.exists():
        try:
            shutil.rmtree(last_run_dir)
        except OSError:
            pass
    last_run_dir.mkdir(parents=True, exist_ok=True)

    # Inputs (whatever Axon dropped into downloads_dir)
    if downloads_dir.exists():
        inp = last_run_dir / "inputs"
        inp.mkdir(exist_ok=True)
        for f in downloads_dir.glob("*.csv"):
            try:
                shutil.copy2(f, inp / f.name)
            except OSError:
                pass

    # Outputs (the generated_ and append_ csvs the pipeline writes back to downloads)
    out = last_run_dir / "outputs"
    out.mkdir(exist_ok=True)
    for f in output_files:
        if f and f.exists():
            try:
                shutil.copy2(f, out / f.name)
            except OSError:
                pass
