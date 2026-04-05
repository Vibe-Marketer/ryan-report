"""Build the Ryan Report desktop app with PyInstaller.

Usage:
    python app/build.py          # Build for current platform
    python app/build.py --debug  # Build with console window for debugging
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
DIST_DIR = REPO_ROOT / "dist"


def _find_playwright_driver() -> str | None:
    """Locate the playwright driver directory (contains the Node.js runtime)."""
    try:
        import playwright
        driver = Path(playwright.__file__).parent / "driver"
        if driver.exists():
            return str(driver)
    except ImportError:
        pass
    return None


def build(debug: bool = False) -> None:
    name = "Ryan Report"
    main_script = str(APP_DIR / "main.py")
    sep = os.pathsep

    cmd = [
        sys.executable, "-m", "PyInstaller",
        main_script,
        "--name", name,
        "--onedir",
        # Bundle the UI files.
        "--add-data", f"{APP_DIR / 'ui'}{sep}ui",
        # Bundle the execution scripts.
        "--add-data", f"{REPO_ROOT / 'execution'}{sep}execution",
        # Bundle the state directory.
        "--add-data", f"{REPO_ROOT / 'state'}{sep}state",
        # Bundle directives.
        "--add-data", f"{REPO_ROOT / 'directives'}{sep}directives",
        # Output location.
        "--distpath", str(DIST_DIR),
        "--workpath", str(REPO_ROOT / "build"),
        "--specpath", str(REPO_ROOT),
        # Clean previous build.
        "--clean",
        "-y",
    ]

    # Bundle Playwright's Node.js driver (required for browser automation).
    pw_driver = _find_playwright_driver()
    if pw_driver:
        cmd.extend(["--add-data", f"{pw_driver}{sep}playwright/driver"])
        print(f"  Bundling Playwright driver from: {pw_driver}")
    else:
        print("  [WARN] Playwright driver not found — download feature won't work")

    # App icon.
    icon_path = APP_DIR / ("icon.icns" if platform.system() == "Darwin" else "icon.png")
    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])

    if not debug:
        if platform.system() == "Darwin":
            cmd.append("--windowed")  # .app bundle on macOS
        else:
            cmd.append("--noconsole")

    # Hidden imports for pywebview and playwright backends.
    hidden = [
        "webview", "webview.platforms.cocoa", "webview.platforms.edgechromium",
        "playwright", "playwright.sync_api", "playwright._impl",
        "playwright._impl._browser_type", "playwright._impl._connection",
    ]
    for imp in hidden:
        cmd.extend(["--hidden-import", imp])

    print(f"Building '{name}' for {platform.system()}...")
    subprocess.run(cmd, check=True)

    app_path = DIST_DIR / name
    if platform.system() == "Darwin":
        app_path = DIST_DIR / f"{name}.app"

    print(f"\nBuild complete! Output: {app_path}")

    # Create DMG on macOS.
    if platform.system() == "Darwin" and not debug:
        dmg_path = DIST_DIR / f"{name}.dmg"
        print(f"Creating DMG: {dmg_path}")
        # Remove old DMG if present.
        dmg_path.unlink(missing_ok=True)
        subprocess.run([
            "hdiutil", "create",
            "-volname", name,
            "-srcfolder", str(DIST_DIR / f"{name}.app"),
            "-ov",
            "-format", "UDZO",  # compressed
            str(dmg_path),
        ], check=True)
        print(f"DMG created: {dmg_path}")
        print(f"\nTo distribute:")
        print(f"  1. Send '{name}.dmg' to the client")
        print(f"  2. They open the DMG and drag the app to Applications")
        print(f"  3. First launch: right-click > Open (bypasses unsigned app warning)")
        print(f"\n  For no warnings: sign with an Apple Developer certificate ($99/year)")


if __name__ == "__main__":
    build(debug="--debug" in sys.argv)
