from __future__ import annotations

import argparse
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Frame, Page, TimeoutError, sync_playwright

CDP_PORT = 9224  # Port for Chrome DevTools Protocol connection to a Chromium browser.
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


def _is_browser_running(exe_path: str) -> bool:
    import subprocess
    system = platform.system()
    if system in {"Darwin", "Linux"}:
        result = subprocess.run(["pgrep", "-f", exe_path], capture_output=True)
        return result.returncode == 0
    if system == "Windows":
        exe_name = Path(exe_path).name
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}"],
            capture_output=True,
            text=True,
        )
        return exe_name.lower() in result.stdout.lower()
    return False


def _stop_browser_process(exe_path: str) -> None:
    import subprocess
    system = platform.system()
    if system in {"Darwin", "Linux"}:
        subprocess.run(["pkill", "-f", exe_path], check=False)
        return
    if system == "Windows":
        exe_name = Path(exe_path).name
        subprocess.run(["taskkill", "/IM", exe_name, "/F"], check=False)


def _cdp_endpoint() -> str:
    return f"http://localhost:{CDP_PORT}"


def launch_context(config: dict[str, Any]) -> tuple[BrowserContext, bool]:
    """Connect to an existing Chromium browser or launch one with CDP enabled.

    Returns (context, launched) where *launched* is True if we started a new
    process (caller should close it), False if we attached to an existing one.
    """
    import subprocess

    browser_cfg = config["browser"]
    playwright = sync_playwright().start()

    # 1) Try connecting to an already-running browser with CDP.
    try:
        browser = playwright.chromium.connect_over_cdp(_cdp_endpoint())
        context = browser.contexts[0]
        context.set_default_timeout(15000)
        print(f"[INFO] Connected to existing browser on port {CDP_PORT}")
        return context, False
    except Exception:
        pass

    # 2) No CDP available — launch (or relaunch) with CDP enabled.
    exe = browser_cfg.get("executable_path")
    profile_dir = browser_cfg.get("profile_directory", "Default")
    user_data = browser_cfg["user_data_dir"]

    if not exe:
        raise RuntimeError("Browser executable path is missing in config.")
    if not Path(exe).exists():
        raise RuntimeError(f"Browser executable does not exist: {exe}")
    if not user_data:
        raise RuntimeError("Browser user data directory is missing in config.")

    if exe and _is_browser_running(exe):
        print("[INFO] Browser is running without CDP. Relaunching with CDP enabled...")
        _stop_browser_process(exe)
        time.sleep(2)

    launch_args = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data}",
        f"--profile-directory={profile_dir}",
    ]

    subprocess.Popen(launch_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(30):
        time.sleep(1)
        try:
            browser = playwright.chromium.connect_over_cdp(_cdp_endpoint())
            context = browser.contexts[0]
            context.set_default_timeout(15000)
            print(f"[INFO] Launched browser with CDP on port {CDP_PORT}")
            return context, True
        except Exception:
            continue

    raise RuntimeError(
        f"Could not connect to browser on port {CDP_PORT} after 30 seconds. "
        f"Try quitting all browser instances and re-running."
    )


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


def maybe_login(page: Page, config: dict[str, Any]) -> None:
    auth = config["auth"]
    base = auth["base_url"].rstrip("/")
    if page.url.rstrip("/") != base:
        page.goto(auth["base_url"], wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

    if page.locator("text=User Name").count() == 0:
        return

    username = auth.get("username", "")
    password = auth.get("password", "")
    if username and password:
        page.locator("#user").fill(username)
        page.locator("#password").fill(password)
        page.locator("input[type='submit'][value='Login']").click()
        page.wait_for_timeout(5000)

    if page.locator("text=User Name").count():
        timeout_seconds = int(auth.get("manual_login_timeout_seconds", 180))
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            if (
                page.locator("text=Trucking").count()
                or page.locator("text=Catom Trucking Inc").count()
            ):
                return
        raise RuntimeError("Browser is not logged in.")


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Axon Ryan reports using a persistent browser profile."
    )
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    downloads_dir = Path(config["downloads"]["directory"])
    downloads_dir.mkdir(parents=True, exist_ok=True)
    context, we_launched = launch_context(config)
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
        if we_launched:
            context.close()


if __name__ == "__main__":
    main()
