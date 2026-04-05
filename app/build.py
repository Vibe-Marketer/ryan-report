"""Build the Ryan Report desktop app with PyInstaller.

Usage:
    python app/build.py          # Build for current platform
    python app/build.py --debug  # Build with console window for debugging
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
DIST_DIR = REPO_ROOT / "dist"


def build(debug: bool = False) -> None:
    name = "Ryan Report"
    main_script = str(APP_DIR / "main.py")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        main_script,
        "--name", name,
        "--onedir",
        # Bundle the UI files.
        "--add-data", f"{APP_DIR / 'ui'}{os.pathsep}ui",
        # Bundle the execution scripts.
        "--add-data", f"{REPO_ROOT / 'execution'}{os.pathsep}execution",
        # Bundle the state directory.
        "--add-data", f"{REPO_ROOT / 'state'}{os.pathsep}state",
        # Bundle directives.
        "--add-data", f"{REPO_ROOT / 'directives'}{os.pathsep}directives",
        # Output location.
        "--distpath", str(DIST_DIR),
        "--workpath", str(REPO_ROOT / "build"),
        "--specpath", str(REPO_ROOT),
        # Clean previous build.
        "--clean",
        "-y",
    ]

    if not debug:
        if platform.system() == "Darwin":
            cmd.append("--windowed")  # .app bundle on macOS
        else:
            cmd.append("--noconsole")

    # Hidden imports for pywebview backends.
    for imp in ["webview", "webview.platforms.cocoa", "webview.platforms.edgechromium"]:
        cmd.extend(["--hidden-import", imp])

    print(f"Building '{name}' for {platform.system()}...")
    print(f"  Command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    print(f"\nBuild complete! Output in: {DIST_DIR / name}")
    if platform.system() == "Darwin":
        print(f"  macOS app: {DIST_DIR / name}.app")
    else:
        print(f"  Windows exe: {DIST_DIR / name / (name + '.exe')}")


if __name__ == "__main__":
    import os
    build(debug="--debug" in sys.argv)
