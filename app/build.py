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
        '#!/bin/sh\n'
        '# Catom preinstall: remove ALL traces of previous installs.\n'
        '# This runs as root during pkg install.\n'
        '\n'
        'CURRENT_USER=$(stat -f \'%Su\' /dev/console 2>/dev/null || echo root)\n'
        'USER_HOME=$(eval echo ~$CURRENT_USER)\n'
        '\n'
        '# Kill any running Catom (but NEVER touch the users Chrome).\n'
        'killall Catom 2>/dev/null || true\n'
        'sleep 1\n'
        '\n'
        '# Remove the installed app.\n'
        'rm -rf /Applications/Catom.app 2>/dev/null || true\n'
        '\n'
        '# Remove stale copies from common locations only (no broad find).\n'
        'rm -rf "$USER_HOME/Desktop/Catom.app" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Downloads/Catom.app" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Documents/Catom.app" 2>/dev/null || true\n'
        'rm -rf /private/tmp/Catom*.app 2>/dev/null || true\n'
        '\n'
        '# Clear ALL user data: config, Chrome profile, caches, state.\n'
        'rm -rf "$USER_HOME/Library/Application Support/Catom" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Library/WebKit/Catom" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Library/Caches/Catom" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Library/Caches/com.andrewnaegele.catom" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Library/Saved Application State/com.andrewnaegele.catom.savedState" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Library/Preferences/com.andrewnaegele.catom.plist" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Library/HTTPStorages/com.andrewnaegele.catom" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/Library/LaunchAgents/com.andrewnaegele.catom.plist" 2>/dev/null || true\n'
        '\n'
        '# Remove package receipts.\n'
        'pkgutil --forget com.andrewnaegele.catom 2>/dev/null || true\n'
        '\n'
        '# Clean Catom copies from Trash.\n'
        'rm -rf "$USER_HOME/.Trash/Catom.app" 2>/dev/null || true\n'
        'rm -rf "$USER_HOME/.Trash/Catom "*.app 2>/dev/null || true\n'
        '\n'
        '# Refresh Spotlight so stale Catom entries disappear.\n'
        'mdimport -d1 /Applications 2>/dev/null || true\n'
        '\n'
        'exit 0\n',
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


def _ms_playwright_cache() -> Path | None:
    """Return the ms-playwright cache root for the current platform."""
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if system == "Linux":
        return home / ".cache" / "ms-playwright"
    if system == "Windows":
        userprofile = Path(os.environ.get("USERPROFILE", str(home)))
        return userprofile / "AppData" / "Local" / "ms-playwright"
    return None


def _install_and_locate_chromium() -> Path | None:
    """Ensure Playwright Chromium is installed locally and return its path.

    The PRD requires the app to ship its own browser; we copy the entire
    chromium-<rev> folder from the ms-playwright cache into the bundle so
    no client-side Chrome install is ever required.
    """
    print("Ensuring Playwright Chromium is installed...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"  [WARN] 'playwright install chromium' failed: {exc}")
        # Continue — maybe it's already installed and we can still find it.

    cache_root = _ms_playwright_cache()
    if not cache_root or not cache_root.exists():
        print(f"  [WARN] ms-playwright cache not found at {cache_root}")
        return None

    candidates = sorted(
        [
            p for p in cache_root.iterdir()
            if p.is_dir()
            and p.name.startswith("chromium-")
            and not p.name.startswith("chromium_headless")
        ],
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        print(f"  [WARN] No chromium-* folder under {cache_root}")
        return None
    chromium_dir = candidates[0]
    print(f"  Bundling Chromium from: {chromium_dir}")
    return chromium_dir


def _fix_playwright_node(app_path: Path) -> None:
    """Replace Playwright's bundled Node.js with a version that works.

    Playwright ships node v24 which has a V8 CodeRange OOM crash on macOS
    arm64 when running the driver script.  We download node v22 LTS which
    is stable and doesn't have this issue.
    """
    system = platform.system()

    if system == "Darwin":
        # Find the bundled node inside the .app or onedir output.
        candidates = list(app_path.rglob("playwright/driver/node"))
        if not candidates:
            print("  [WARN] Playwright driver/node not found in bundle — skipping fix")
            return
        bundled_node = candidates[0]

        # Download node v22 LTS for arm64 macOS.
        import urllib.request
        import tarfile
        node_url = "https://nodejs.org/dist/v22.16.0/node-v22.16.0-darwin-arm64.tar.gz"
        tar_path = Path(tempfile.mkdtemp()) / "node.tar.gz"
        print("  Downloading node v22 LTS for arm64...")
        urllib.request.urlretrieve(node_url, tar_path)
        with tarfile.open(tar_path) as tf:
            member = tf.getmember("node-v22.16.0-darwin-arm64/bin/node")
            member.name = "node"
            tf.extract(member, bundled_node.parent)
        print(f"  Replaced bundled node: {bundled_node}")

    elif system == "Windows":
        candidates = list(app_path.rglob("playwright/driver/node.exe"))
        if not candidates:
            print("  [WARN] Playwright driver/node.exe not found — skipping fix")
            return
        bundled_node = candidates[0]

        import urllib.request
        import zipfile
        node_url = "https://nodejs.org/dist/v22.16.0/node-v22.16.0-win-x64.zip"
        zip_path = Path(tempfile.mkdtemp()) / "node.zip"
        print("  Downloading node v22 LTS for Windows x64...")
        urllib.request.urlretrieve(node_url, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open("node-v22.16.0-win-x64/node.exe") as src:
                bundled_node.write_bytes(src.read())
        print(f"  Replaced bundled node.exe: {bundled_node}")


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

    # Locate Chromium NOW (before PyInstaller runs) but DON'T pass it to
    # PyInstaller. PyInstaller tries to ad-hoc sign every binary it bundles,
    # and chokes on Chromium because it's a nested .app with its own
    # framework structure. We copy it manually after PyInstaller finishes.
    chromium_dir = _install_and_locate_chromium()
    if not chromium_dir:
        print("  [ERROR] Chromium not bundled — app will fail at runtime!")
        print("  [ERROR] Run 'playwright install chromium' and rebuild.")

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
        # pdfplumber for the Distribution Report parsing. Without these the
        # PyInstaller bundle silently lacks PDF support on Windows because
        # there's no system pdftotext binary to fall back to.
        "pdfplumber", "pdfminer", "pdfminer.six", "pdfminer.high_level",
        # certifi: provides the CA bundle our ssl_context() pins. Without it
        # the frozen build has no CA store and every HTTPS call (update check,
        # installer download, distribution PDF, Claude API) fails with URLError.
        "certifi",
    ]
    for imp in hidden:
        cmd.extend(["--hidden-import", imp])

    # Ship certifi's cacert.pem DATA file (not just the module) so
    # certifi.where() resolves to a real path inside the frozen app.
    cmd.extend(["--collect-data", "certifi"])

    # Exclude numpy/pandas from the bundle. openpyxl optionally imports numpy
    # and, at import time, builds a tuple including numpy.short/ushort/etc.
    # PyInstaller drags an INCOMPLETE numpy into the frozen app -- importable
    # but missing those attributes -- so openpyxl's `if NUMPY:` block raises
    # `module 'numpy' has no attribute 'short'` and the build step crashes
    # ([ERROR] Build failed: module 'numpy' has no attribute 'short'). We use
    # numpy nowhere (our code reads CSV/xlsx via openpyxl's pure-Python path;
    # pdfplumber needs only pdfminer/Pillow/pypdfium2), so dropping it makes
    # openpyxl's `import numpy` fail cleanly (ImportError -> NUMPY=False) and
    # the build proceeds. Bonus: a smaller installer.
    for _excluded in ("numpy", "pandas"):
        cmd.extend(["--exclude-module", _excluded])

    print(f"Building '{name}' for {platform.system()}...")
    _run(cmd)

    # Copy Chromium into the onedir _internal/ folder BEFORE wrapping into
    # an .app bundle. PyInstaller never touches these files, so its
    # signing pass cannot break Chromium's nested bundle structure.
    if chromium_dir:
        dest = DIST_DIR / name / "_internal" / "playwright-browsers" / chromium_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        print(f"  Copying Chromium into onedir bundle: {dest}")
        shutil.copytree(
            chromium_dir,
            dest,
            symlinks=True,
            copy_function=shutil.copy2,
        )

    app_path = DIST_DIR / name
    if platform.system() == "Darwin":
        app_path = _make_macos_app_bundle(name)

    print(f"\nBuild complete! Output: {app_path}")

    # Replace Playwright's bundled Node.js with a compatible version.
    # Playwright ships node v24 which has a V8 CodeRange OOM bug on arm64.
    _fix_playwright_node(app_path)

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
        # Stage the .app inside a temporary root so pkgbuild places it
        # exactly at /Applications/Catom.app (--component is unreliable).
        pkg_root = Path(tempfile.mkdtemp(prefix="catom-pkg-root-"))
        subprocess.run(
            ["ditto", str(app_path), str(pkg_root / f"{name}.app")],
            check=True,
        )
        # Create a component plist that disables bundle relocation.
        # Without this, macOS finds existing Catom.app copies by bundle ID
        # and installs THERE instead of /Applications.
        comp_plist = Path(tempfile.mkdtemp()) / "component.plist"
        comp_plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<array>\n<dict>\n'
            '  <key>BundleIsRelocatable</key>\n  <false/>\n'
            '  <key>BundleOverwriteAction</key>\n  <string>upgrade</string>\n'
            f'  <key>RootRelativeBundlePath</key>\n  <string>{name}.app</string>\n'
            '</dict>\n</array>\n</plist>\n',
            encoding="utf-8",
        )
        pkg_cmd = [
            "pkgbuild",
            "--root",
            str(pkg_root),
            "--component-plist",
            str(comp_plist),
            "--install-location",
            "/Applications",
            "--scripts",
            str(_make_pkg_scripts_dir()),
            "--identifier",
            "com.andrewnaegele.catom",
            "--version",
            "1.0.0",
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
        print("\nTo distribute:")
        print(f"  1. Send '{name}.dmg' or '{name}.pkg' to the client")
        print("  2. DMG: drag the app to Applications")
        print("  3. PKG: run installer to place app in /Applications")
        if not identity:
            print("\n  Note: build is ad hoc signed only. Install a valid Developer ID Application")
            print("  identity and export CATOM_CODESIGN_IDENTITY to remove Gatekeeper warnings.")


if __name__ == "__main__":
    build(debug="--debug" in sys.argv)
