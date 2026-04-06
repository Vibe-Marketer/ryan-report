"""Build the Catom desktop app with PyInstaller.

Usage:
    python app/build.py          # Build for current platform
    python app/build.py --debug  # Build with console window for debugging
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
DIST_DIR = Path(os.environ.get("CATOM_DIST_DIR", str(REPO_ROOT / "dist"))).expanduser()


def _codesign_identity() -> str | None:
    identity = os.environ.get("CATOM_CODESIGN_IDENTITY", "").strip()
    return identity or None


def _installer_identity() -> str | None:
    identity = os.environ.get("CATOM_INSTALLER_IDENTITY", "").strip()
    return identity or None


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _make_pkg_scripts_dir() -> Path:
    scripts_dir = Path(tempfile.mkdtemp(prefix="catom-pkg-scripts-"))
    preinstall = scripts_dir / "preinstall"
    preinstall.write_text(
        "#!/bin/sh\n"
        "set -e\n"
        "if [ -d \"/Applications/Catom.app\" ]; then\n"
        "  rm -rf \"/Applications/Catom.app\"\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    preinstall.chmod(0o755)
    return scripts_dir


def _make_macos_app_bundle(name: str) -> Path:
    """Wrap the PyInstaller onedir output in a real .app bundle.

    PyInstaller's raw onedir folder is left in dist/<name>. This function
    creates dist/<name>.app as the launchable artifact and embeds the onedir
    payload inside Contents/Resources/app.
    """
    app_dir = DIST_DIR / f"{name}.app"
    payload_dir = DIST_DIR / name
    contents = app_dir / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    embedded = resources / "app"
    icon_src = APP_DIR / "icon.icns"

    if app_dir.exists():
        shutil.rmtree(app_dir)

    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    if embedded.exists():
        shutil.rmtree(embedded)
    shutil.copytree(payload_dir, embedded)

    if icon_src.exists():
        shutil.copy2(icon_src, resources / "icon.icns")

    launcher = macos / name
    launcher.write_text(
        "#!/bin/sh\n"
        "DIR=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\n"
        "APP_ROOT=\"$DIR/../Resources/app\"\n"
        "cd \"$APP_ROOT\"\n"
        f"exec \"$APP_ROOT/{name}\" \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    info_plist = contents / "Info.plist"
    info_plist.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleDisplayName</key>
  <string>{name}</string>
  <key>CFBundleExecutable</key>
  <string>{name}</string>
  <key>CFBundleIconFile</key>
  <string>icon.icns</string>
  <key>CFBundleIdentifier</key>
  <string>com.andrewnaegele.catom</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>{name}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )

    return app_dir


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
    name = "Catom"
    main_script = str(APP_DIR / "main.py")
    sep = os.pathsep
    staging_root = Path(tempfile.mkdtemp(prefix="catom-build-"))
    execution_stage = staging_root / "execution"
    shutil.copytree(
        REPO_ROOT / "execution",
        execution_stage,
        ignore=shutil.ignore_patterns("browser_config.json", "__pycache__"),
    )

    cmd = [
        sys.executable, "-m", "PyInstaller",
        main_script,
        "--name", name,
        "--onedir",
        # Bundle the UI files.
        "--add-data", f"{APP_DIR / 'ui'}{sep}ui",
        # Bundle the execution scripts.
        "--add-data", f"{execution_stage}{sep}execution",
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
        "openpyxl",
    ]
    for imp in hidden:
        cmd.extend(["--hidden-import", imp])

    print(f"Building '{name}' for {platform.system()}...")
    _run(cmd)

    app_path = DIST_DIR / name
    if platform.system() == "Darwin":
        app_path = _make_macos_app_bundle(name)

    print(f"\nBuild complete! Output: {app_path}")

    # macOS packaging/signing.
    if platform.system() == "Darwin" and not debug:
        identity = _codesign_identity()
        sign_label = identity if identity else "-"
        if identity:
            print(f"Signing app with identity: {identity}")
        else:
            print("No Developer ID identity configured. Applying ad hoc signature for local verification.")

        _run([
            "codesign",
            "--force",
            "--deep",
            "--sign",
            sign_label,
            "--options",
            "runtime",
            "--timestamp",
            str(app_path),
        ])
        _run([
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            "--verbose=2",
            str(app_path),
        ])

        pkg_path = DIST_DIR / f"{name}.pkg"
        pkg_path.unlink(missing_ok=True)
        print(f"Creating PKG: {pkg_path}")
        pkg_cmd = [
            "pkgbuild",
            "--component",
            str(app_path),
            "--install-location",
            "/Applications",
            "--scripts",
            str(_make_pkg_scripts_dir()),
        ]
        installer_identity = _installer_identity()
        if installer_identity:
            print(f"Signing installer with identity: {installer_identity}")
            pkg_cmd.extend(["--sign", installer_identity])
        pkg_cmd.append(str(pkg_path))
        _run(pkg_cmd)
        print(f"PKG created: {pkg_path}")
        dmg_path = DIST_DIR / f"{name}.dmg"
        print(f"Creating DMG: {dmg_path}")
        dmg_path.unlink(missing_ok=True)
        try:
            _run([
                "hdiutil", "create",
                "-volname", name,
                "-srcfolder", str(DIST_DIR / f"{name}.app"),
                "-ov",
                "-format", "UDZO",
                str(dmg_path),
            ])
            print(f"DMG created: {dmg_path}")
        except subprocess.CalledProcessError as exc:
            print(f"[WARN] DMG creation failed: {exc}")
            print("[WARN] PKG is still available for install/testing.")
        print(f"\nTo distribute:")
        print(f"  1. Send '{name}.dmg' or '{name}.pkg' to the client")
        print(f"  2. DMG: drag the app to Applications")
        print(f"  3. PKG: run installer to place app in /Applications")
        if not identity:
            print("\n  Note: build is ad hoc signed only. Install a valid Developer ID Application")
            print("  identity and export CATOM_CODESIGN_IDENTITY to remove Gatekeeper warnings.")


if __name__ == "__main__":
    build(debug="--debug" in sys.argv)
