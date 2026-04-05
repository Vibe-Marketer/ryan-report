from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, TimeoutError, sync_playwright


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def launch_context(config: dict[str, Any]) -> BrowserContext:
    browser = config["browser"]
    downloads_dir = Path(config["downloads"]["directory"])
    downloads_dir.mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    engine = getattr(playwright, browser.get("engine", "chromium"))
    context = engine.launch_persistent_context(
        user_data_dir=browser["user_data_dir"],
        headless=browser.get("headless", False),
        executable_path=browser.get("executable_path"),
        args=[f"--profile-directory={browser.get('profile_directory', 'Default')}"]
        if browser.get("profile_directory")
        else [],
        accept_downloads=True,
        downloads_path=str(downloads_dir),
        viewport={"width": 1600, "height": 1000},
    )
    context.set_default_timeout(15000)
    context.on("close", lambda: playwright.stop())
    return context


def first_page(context: BrowserContext) -> Page:
    return context.pages[0] if context.pages else context.new_page()


def maybe_login(page: Page, config: dict[str, Any]) -> None:
    auth = config["auth"]
    page.goto(auth["base_url"], wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    if page.locator("text=User Name").count() == 0:
        return

    username = auth.get("username", "")
    password = auth.get("password", "")
    if username and password:
        page.locator("input").nth(0).fill(username)
        page.locator("input").nth(1).fill(password)
        page.get_by_role("button", name="Login").click()
        page.wait_for_timeout(3000)

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


def click_text(page: Page, text: str) -> None:
    exact = page.get_by_text(text, exact=True)
    if exact.count():
        exact.first.click()
        return
    fuzzy = page.get_by_text(text)
    if fuzzy.count():
        fuzzy.first.click()
        return
    raise RuntimeError(f"Could not find visible text: {text}")


def run_step(page: Page, step: dict[str, Any]) -> None:
    action = step["action"]
    if action == "goto":
        page.goto(step["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(step.get("wait_ms", 1500))
        return
    if action == "click_text":
        click_text(page, step["text"])
        page.wait_for_timeout(step.get("wait_ms", 1000))
        return
    raise RuntimeError(f"Unsupported action: {action}")


def run_report(page: Page, report: dict[str, Any], downloads_dir: Path) -> Path | None:
    for step in report["steps"]:
        if step["action"] == "click_text" and step.get("text") == "Export":
            with page.expect_download(
                timeout=step.get("timeout_ms", 60000)
            ) as download_info:
                run_step(page, step)
            download = download_info.value
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
    context = launch_context(config)
    try:
        page = first_page(context)
        maybe_login(page, config)
        for report in config["reports"]:
            if report.get("enabled", True) is False:
                continue
            try:
                run_report(page, report, downloads_dir)
            except TimeoutError as exc:
                raise RuntimeError(
                    f"Timed out while downloading {report['name']}: {exc}"
                ) from exc
    finally:
        context.close()


if __name__ == "__main__":
    main()
