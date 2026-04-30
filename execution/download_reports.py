from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError,
    sync_playwright,
)

VIEWPORT = {"width": 1600, "height": 1000}


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)

    def _expand(obj: Any) -> Any:
        if isinstance(obj, str):
            return os.path.expandvars(obj)
        if isinstance(obj, dict):
            return {k: _expand(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_expand(v) for v in obj]
        return obj
    return _expand(cfg)


def _bundled_chromium_executable() -> str | None:
    """Return path to the Chromium binary bundled inside the frozen app.

    In a PyInstaller bundle, build.py copies the entire chromium-<rev>
    folder from the ms-playwright cache into <MEIPASS>/playwright-browsers/.
    In dev mode, return None so Playwright uses its default cache.
    """
    if not getattr(sys, "frozen", False):
        return None
    base = Path(sys._MEIPASS) / "playwright-browsers"
    if not base.exists():
        return None
    candidates = [
        d for d in base.iterdir()
        if d.is_dir() and d.name.startswith("chromium-")
    ]
    if not candidates:
        return None
    chromium_dir = candidates[0]
    system = platform.system()
    if system == "Darwin":
        exe = (
            chromium_dir / "chrome-mac" / "Chromium.app" / "Contents"
            / "MacOS" / "Chromium"
        )
    elif system == "Windows":
        exe = chromium_dir / "chrome-win" / "chrome.exe"
    else:
        exe = chromium_dir / "chrome-linux" / "chrome"
    return str(exe) if exe.exists() else None


def _app_browser_profile_dir() -> str:
    """Return the app-private browser profile directory.

    Login state, cookies, and session data persist here across runs. Lives
    under the user's app-data area, separate from any other browser profile.
    """
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        base = home / "Library" / "Application Support" / "Catom" / "browser-profile"
    elif system == "Windows":
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        base = appdata / "Catom" / "browser-profile"
    else:
        base = home / ".config" / "catom" / "browser-profile"
    base.mkdir(parents=True, exist_ok=True)
    return str(base)


def launch_context(config: dict[str, Any]) -> tuple[BrowserContext, Playwright]:
    """Launch the bundled Chromium with the app-private profile.

    The PRD requires the app to manage its own browser end-to-end: never
    connect to a user-installed Chrome, never read a browser executable
    path from config, never share a profile with the user's normal browser.

    Returns (context, playwright). Caller MUST call close_session() when done.
    """
    # Fix Playwright's driver path inside a PyInstaller bundle. The driver
    # ships a Node binary; build.py replaces v24 (which has a V8 CodeRange
    # OOM bug on macOS arm64) with v22 LTS. We point Playwright at the
    # bundled cli.js + node so it doesn't try to reinstall.
    if getattr(sys, "frozen", False):
        driver_dir = Path(sys._MEIPASS) / "playwright" / "driver"
        cli_js = driver_dir / "package" / "cli.js"
        node_bin = str(
            driver_dir / ("node.exe" if platform.system() == "Windows" else "node")
        )
        if cli_js.exists():
            def _patched():
                return (node_bin, str(cli_js))
            import playwright._impl._driver as _drv
            _drv.compute_driver_executable = _patched
            import playwright._impl._transport as _transport
            _transport.compute_driver_executable = _patched

    try:
        playwright = sync_playwright().start()
    except Exception as start_err:
        raise RuntimeError(
            f"Could not start Playwright browser engine: {start_err}. "
            f"Try restarting the app."
        )

    user_data_dir = _app_browser_profile_dir()
    chromium_exe = _bundled_chromium_executable()

    launch_kwargs: dict[str, Any] = {
        "user_data_dir": user_data_dir,
        "headless": False,
        "viewport": VIEWPORT,
        "accept_downloads": True,
        "args": [
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }
    if chromium_exe:
        launch_kwargs["executable_path"] = chromium_exe
        print(f"[INFO] Launching bundled Chromium: {chromium_exe}")
    else:
        print("[INFO] Launching Playwright Chromium (dev mode, no bundled binary)")

    try:
        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
    except Exception as exc:
        try:
            playwright.stop()
        except Exception:
            pass
        raise RuntimeError(
            f"Could not launch the bundled browser: {exc}. "
            f"Try reinstalling Catom, or in dev mode run "
            f"'python -m playwright install chromium'."
        )

    context.set_default_timeout(15000)
    return context, playwright


def close_session(context: BrowserContext, playwright: Playwright) -> None:
    """Close a context+playwright pair returned by launch_context()."""
    try:
        context.close()
    except Exception:
        pass
    try:
        playwright.stop()
    except Exception:
        pass


def find_axon_page(context: BrowserContext, base_url: str) -> Page:
    """Find an existing logged-in Axon page, or create a new one."""
    base = base_url.rstrip("/")
    for page in context.pages:
        if page.url.rstrip("/") == base and page.get_by_text("Trucking").count() > 0:
            print("[INFO] Reusing logged-in Axon tab")
            return page
    for page in context.pages:
        if base in page.url:
            return page
    return context.new_page()


def _detect_2fa_prompt(page: Page) -> bool:
    """Return True if the page is showing a 2FA / verification code prompt."""
    content = page.content().lower()
    indicators = ["verification code", "two-factor", "2fa", "security code",
                  "enter code", "enter the code", "one-time"]
    return any(ind in content for ind in indicators)


def _on_dashboard(page: Page) -> bool:
    return (
        page.locator("text=Trucking").count() > 0
        or page.locator("text=Catom Trucking Inc").count() > 0
    )


def maybe_login(page: Page, config: dict[str, Any]) -> None:
    auth = config["auth"]
    base = auth["base_url"].rstrip("/")
    if page.url.rstrip("/") != base:
        page.goto(auth["base_url"], wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

    page.wait_for_timeout(2000)

    if page.locator("text=User Name").count() == 0:
        return

    username = auth.get("username", "").strip()
    password = auth.get("password", "").strip()
    if username and password:
        # Axon's login fields may start as disabled/readonly.
        # Use JS to force them editable before filling.
        page.evaluate("""() => {
            const user = document.getElementById('user');
            const pass = document.getElementById('password');
            if (user) { user.disabled = false; user.readOnly = false; user.value = ''; }
            if (pass) { pass.disabled = false; pass.readOnly = false; pass.value = ''; }
        }""")
        page.wait_for_timeout(500)
        page.locator("#user").fill(username)
        page.wait_for_timeout(300)
        page.locator("#password").fill(password)
        page.wait_for_timeout(300)
        page.locator("input[type='submit'][value='Login']").click()
        page.wait_for_timeout(5000)

    if _on_dashboard(page):
        return

    # Not on dashboard — likely 2FA or verification code needed.
    # The browser is visible. Tell the user to enter the code there.
    print("[INFO] A verification code may be required.")
    print("[INFO] Check your email for the code and enter it in the browser window.")
    print("[INFO] Waiting up to 3 minutes for you to complete login...")

    timeout_seconds = int(auth.get("manual_login_timeout_seconds", 180))
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        if _on_dashboard(page):
            return
    raise RuntimeError("Browser is not logged in. Check your credentials and try again.")


# ---------------------------------------------------------------------------
# Axon TMS interaction helpers
#
# The Axon UI has three layers:
#   1. Top tab bar: <div class="su-tab-text"> elements (e.g. "Trucking")
#   2. Content iframe (about:srcdoc): <a> links with javascript:suIframeSend
#   3. Main frame buttons: <button class="su-button"> (e.g. "Export")
# ---------------------------------------------------------------------------

def _click_tab(page: Page, name: str) -> None:
    """Click a top-level tab by name (e.g. 'Trucking')."""
    page.evaluate(f'''() => {{
        const tabs = document.querySelectorAll('div.su-tab-text');
        for (const t of tabs) {{
            if (t.textContent.trim() === {json.dumps(name)}) {{
                t.click();
                return;
            }}
        }}
        throw new Error('Tab not found: ' + {json.dumps(name)});
    }}''')


def _click_menu_link(page: Page, text: str, timeout: int = 15000) -> None:
    """Click an <a> link inside any sub-frame by its exact text.

    Uses JS element.click() to avoid iframe pointer-event interception.
    Polls all frames until the link appears (the content iframe reloads
    after tab navigation).
    """
    escaped = json.dumps(text)
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                clicked = frame.evaluate(f'''() => {{
                    const links = document.querySelectorAll('a');
                    for (const a of links) {{
                        if (a.textContent.trim() === {escaped}) {{
                            a.click();
                            return true;
                        }}
                    }}
                    return false;
                }}''')
                if clicked:
                    return
            except Exception:
                pass
        page.wait_for_timeout(500)
    raise RuntimeError(f"Menu link not found: {text}")


def _click_button(page: Page, text: str) -> None:
    """Click a <button class='su-button'> in the main frame by text."""
    page.evaluate(f'''() => {{
        const buttons = document.querySelectorAll('button.su-button');
        for (const b of buttons) {{
            if (b.textContent.trim() === {json.dumps(text)}) {{
                b.click();
                return;
            }}
        }}
        throw new Error('Button not found: ' + {json.dumps(text)});
    }}''')


def run_step(page: Page, step: dict[str, Any]) -> None:
    action = step["action"]
    wait_ms = step.get("wait_ms", 2000)

    if action == "click_tab":
        print(f"  tab: {step['name']}")
        _click_tab(page, step["name"])

    elif action == "click_menu":
        print(f"  menu: {step['text']}")
        _click_menu_link(page, step["text"])

    elif action == "click_button":
        print(f"  button: {step['text']}")
        _click_button(page, step["text"])

    else:
        raise RuntimeError(f"Unsupported action: {action}")

    page.wait_for_timeout(wait_ms)


def run_report(page: Page, report: dict[str, Any], downloads_dir: Path) -> Path | None:
    print(f"\n--- {report['name']} ---")
    for step in report["steps"]:
        if step.get("triggers_download"):
            with page.expect_download(timeout=step.get("timeout_ms", 60000)) as dl:
                run_step(page, step)
            download = dl.value
            target = downloads_dir / download.suggested_filename
            download.save_as(str(target))
            return target
        run_step(page, step)
    return None


def run_single_report(
    config: dict[str, Any],
    report: dict[str, Any],
    log=None,
) -> Path | None:
    """Launch browser, log in, run one report path, cleanup.

    Single shared entry point used by both the CLI (`main`) and the desktop
    app's test-run API, so browser lifecycle lives in one place.
    """
    _log = log or (lambda msg: print(msg))
    downloads_dir = Path(config["downloads"]["directory"])
    downloads_dir.mkdir(parents=True, exist_ok=True)

    _log("[INFO] Launching bundled browser...")
    context, pw = launch_context(config)
    _log("[INFO] Browser ready")
    try:
        page = find_axon_page(context, config["auth"]["base_url"])
        page.set_viewport_size(VIEWPORT)
        _log("[INFO] Logging in to Axon...")
        maybe_login(page, config)
        _log("[INFO] Logged in to Axon")
        _log(f"[INFO] Running path: {report['name']}...")
        return run_report(page, report, downloads_dir)
    finally:
        close_session(context, pw)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Axon Ryan reports using the bundled browser."
    )
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    downloads_dir = Path(config["downloads"]["directory"])
    downloads_dir.mkdir(parents=True, exist_ok=True)
    context, pw = launch_context(config)
    try:
        page = find_axon_page(context, config["auth"]["base_url"])
        page.set_viewport_size(VIEWPORT)
        maybe_login(page, config)

        for report in config["reports"]:
            if report.get("enabled", True) is False:
                continue
            try:
                result = run_report(page, report, downloads_dir)
                if result:
                    print(f"[OK] Downloaded {report['name']}: {result}")
            except TimeoutError as exc:
                raise RuntimeError(
                    f"Timed out while downloading {report['name']}: {exc}"
                ) from exc
    finally:
        close_session(context, pw)


if __name__ == "__main__":
    main()
