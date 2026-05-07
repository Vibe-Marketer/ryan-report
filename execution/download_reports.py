from __future__ import annotations

import argparse
import datetime
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
PATH_CONFIG_KEYS = {
    "directory",
    "executable_path",
    "historical_ryan",
    "path",
    "user_data_dir",
}


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)

    def _expand(obj: Any, key: str = "") -> Any:
        if isinstance(obj, str):
            if key in PATH_CONFIG_KEYS:
                return os.path.expandvars(obj)
            return obj
        if isinstance(obj, dict):
            return {k: _expand(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_expand(v, key) for v in obj]
        return obj
    return _expand(cfg)


def _bundled_chromium_executable() -> str | None:
    """Return path to the Chromium binary bundled inside the frozen app.

    In a PyInstaller bundle, build.py copies the entire chromium-<rev>
    folder from the ms-playwright cache into <MEIPASS>/playwright-browsers/.
    In dev mode, return None so Playwright uses its default cache.

    Modern Playwright ships "Google Chrome for Testing" in arch-specific
    folders (chrome-mac-arm64, chrome-mac-x64, chrome-win-x64, etc.) so we
    glob rather than hardcode names.
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
        # chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/<same name>
        # (legacy: chrome-mac/Chromium.app/.../Chromium)
        for arch_dir in chromium_dir.glob("chrome-mac*"):
            for app_dir in arch_dir.glob("*.app"):
                exe = app_dir / "Contents" / "MacOS" / app_dir.stem
                if exe.exists():
                    return str(exe)
        return None
    if system == "Windows":
        for win_dir in chromium_dir.glob("chrome-win*"):
            exe = win_dir / "chrome.exe"
            if exe.exists():
                return str(exe)
        return None
    # Linux
    for lin_dir in chromium_dir.glob("chrome-linux*"):
        exe = lin_dir / "chrome"
        if exe.exists():
            return str(exe)
    return None


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
            # Disable Chrome's password manager + autofill — they otherwise
            # overwrite our programmatic fill with the previously-saved
            # value, which made password updates in Settings ineffective.
            "--disable-features=PasswordManager,AutofillServerCommunication,"
            "PasswordManagerOnboarding,PasswordGeneration,AutofillEnableAccountWalletStorage",
            "--password-store=basic",
            "--disable-save-password-bubble",
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
    # Check for the post-login tab bar element rather than branding text:
    # words like "Trucking" / "Catom Trucking Inc" appear on the login and
    # 2FA screens too (page chrome, footer), causing maybe_login() to
    # return immediately and the browser to close before the user can
    # complete 2FA. The su-tab-text class only renders after auth.
    if _detect_2fa_prompt(page):
        return False
    return page.locator("div.su-tab-text").count() > 0


def _pw_fp(pw: str) -> str:
    """Return a non-revealing fingerprint of a password for logging."""
    if not pw:
        return "(empty)"
    if len(pw) <= 4:
        return f"len={len(pw)} first={pw[0]!r}"
    return f"len={len(pw)} first2={pw[:2]!r} last2={pw[-2:]!r}"


def _log_path() -> Path:
    """Same catom.log used by app/main.py's _file_log."""
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        base = home / "Library" / "Application Support" / "Catom"
    elif system == "Windows":
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        base = appdata / "Catom"
    else:
        base = home / ".config" / "catom"
    base.mkdir(parents=True, exist_ok=True)
    return base / "catom.log"


def _flog(msg: str) -> None:
    """Write to catom.log AND stdout. Survives --windowed PyInstaller mode."""
    print(msg)
    try:
        import datetime as _dt
        with _log_path().open("a", encoding="utf-8") as f:
            ts = _dt.datetime.now().isoformat(timespec="seconds")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def maybe_login(page: Page, config: dict[str, Any]) -> None:
    auth = config["auth"]
    base = auth["base_url"].rstrip("/")
    _flog(f"[LOGIN] base_url={base}")
    _flog(f"[LOGIN] username from config={auth.get('username','')!r}")
    _flog(f"[LOGIN] password fingerprint={_pw_fp(auth.get('password',''))}")
    if page.url.rstrip("/") != base:
        page.goto(auth["base_url"], wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

    page.wait_for_timeout(2000)

    if page.locator("text=User Name").count() == 0:
        _flog("[LOGIN] No User Name field found — assuming already logged in")
        return

    username = auth.get("username", "").strip()
    password = auth.get("password", "").strip()
    _flog(f"[LOGIN] About to fill — username={username!r}, password fp={_pw_fp(password)}")
    if username and password:
        # Axon's login fields may start as disabled/readonly.
        # Use JS to force them editable before filling.
        page.evaluate("""() => {
            const user = document.getElementById('user');
            const pass = document.getElementById('password');
            if (user) { user.disabled = false; user.readOnly = false; user.value = ''; user.setAttribute('autocomplete', 'off'); }
            if (pass) { pass.disabled = false; pass.readOnly = false; pass.value = ''; pass.setAttribute('autocomplete', 'new-password'); }
        }""")
        page.wait_for_timeout(500)
        page.locator("#user").fill(username)
        page.wait_for_timeout(300)
        page.locator("#password").fill(password)
        # Read back what's actually in the field so we know if anything
        # overwrote our fill.
        try:
            actual = page.evaluate("document.getElementById('password').value")
            _flog(f"[LOGIN] Field value after fill — fp={_pw_fp(actual)}")
        except Exception as exc:
            _flog(f"[LOGIN] Could not read back field: {exc}")
        # Force the value through input/change events so Axon's JS sees what
        # we typed, defeating any leftover autofill that might re-populate.
        page.evaluate(
            f"""(pwd) => {{
                const p = document.getElementById('password');
                if (p) {{
                    p.value = pwd;
                    p.dispatchEvent(new Event('input', {{bubbles: true}}));
                    p.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}""",
            password,
        )
        page.wait_for_timeout(300)
        page.locator("input[type='submit'][value='Login']").click()
        page.wait_for_timeout(5000)

    if _on_dashboard(page):
        return

    # Not on dashboard — likely 2FA or verification code needed.
    # The browser is visible. Tell the user to enter the code there.
    timeout_seconds = int(auth.get("manual_login_timeout_seconds", 300))
    print("[INFO] A verification code may be required.")
    print("[INFO] Check your email for the code and enter it in the browser window.")
    print(f"[INFO] Waiting up to {timeout_seconds // 60} minutes for you to complete login...")

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


def _set_end_date_today(page: Page, value: str | None = None) -> str:
    """Set the current report page's end/to date field to today's date.

    Axon report screens are not consistent about date input markup, so this
    prefers fields labeled/named like end/to dates and falls back to the last
    visible date-like input on the page.
    """
    display_value = value or datetime.date.today().strftime("%m/%d/%Y")
    iso_value = datetime.datetime.strptime(display_value, "%m/%d/%Y").strftime("%Y-%m-%d")
    result = page.evaluate(
        """({displayValue, isoValue}) => {
            const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && rect.width > 0
                    && rect.height > 0;
            };
            const labelText = (el) => {
                const parts = [];
                for (const attr of ['aria-label', 'placeholder', 'name', 'id', 'title']) {
                    if (el.getAttribute(attr)) parts.push(el.getAttribute(attr));
                }
                if (el.id) {
                    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (label) parts.push(label.textContent || '');
                }
                const wrappingLabel = el.closest('label');
                if (wrappingLabel) parts.push(wrappingLabel.textContent || '');
                let parent = el.parentElement;
                for (let i = 0; parent && i < 3; i += 1, parent = parent.parentElement) {
                    parts.push(parent.textContent || '');
                }
                return parts.join(' ').replace(/\\s+/g, ' ').toLowerCase();
            };
            const dateish = Array.from(document.querySelectorAll('input'))
                .filter((el) => {
                    const type = (el.getAttribute('type') || 'text').toLowerCase();
                    if (['hidden', 'button', 'submit', 'checkbox', 'radio', 'file'].includes(type)) return false;
                    const text = labelText(el);
                    return visible(el) && (
                        type === 'date'
                        || text.includes('date')
                        || /\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}/.test(el.value || '')
                    );
                });
            const preferred = dateish.filter((el) => {
                const text = labelText(el);
                return /\\b(end|to|through|thru|until)\\b/.test(text);
            });
            const target = preferred[preferred.length - 1] || dateish[dateish.length - 1];
            if (!target) {
                return {ok: false, reason: 'No visible date input found'};
            }
            const type = (target.getAttribute('type') || 'text').toLowerCase();
            const newValue = type === 'date' ? isoValue : displayValue;
            target.disabled = false;
            target.readOnly = false;
            target.focus();
            target.value = newValue;
            target.dispatchEvent(new Event('input', {bubbles: true}));
            target.dispatchEvent(new Event('change', {bubbles: true}));
            target.dispatchEvent(new Event('blur', {bubbles: true}));
            return {
                ok: true,
                value: newValue,
                matched: labelText(target).slice(0, 160),
                candidateCount: dateish.length,
            };
        }""",
        {"displayValue": display_value, "isoValue": iso_value},
    )
    if not result.get("ok"):
        raise RuntimeError(f"Could not set report end date: {result.get('reason')}")
    return str(result.get("value", display_value))


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

    elif action in ("set_end_date_today", "set_report_end_date_today"):
        value = step.get("value") or step.get("date")
        result = _set_end_date_today(page, value=value)
        print(f"  end date: {result}")

    else:
        raise RuntimeError(f"Unsupported action: {action}")

    page.wait_for_timeout(wait_ms)


def run_report(page: Page, report: dict[str, Any], downloads_dir: Path) -> Path | None:
    print(f"\n--- {report['name']} ---")
    report_name = str(report.get("name", "")).lower()
    did_set_end_date = False
    for step in report["steps"]:
        if step.get("action") in ("set_end_date_today", "set_report_end_date_today"):
            did_set_end_date = True
        if step.get("triggers_download"):
            if report_name == "order_master" and not did_set_end_date:
                result = _set_end_date_today(page)
                print(f"  end date: {result}")
                page.wait_for_timeout(500)
                did_set_end_date = True
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
