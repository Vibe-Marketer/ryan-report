from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _python_exe() -> str:
    """Return a usable Python interpreter, even inside a PyInstaller bundle."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    import shutil
    for candidate in ("python3", "python"):
        found = shutil.which(candidate)
        if found:
            return found
    return sys.executable


def run(cmd: list[str], workdir: Path) -> None:
    completed = subprocess.run(cmd, cwd=workdir)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _downloads_dir_from_config(config_path: str) -> str:
    """Read the downloads directory from the browser config."""
    p = Path(config_path)
    if p.exists():
        with p.open() as f:
            cfg = json.load(f)
        raw = cfg.get("downloads", {}).get("directory", "")
        return os.path.expandvars(raw)
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Axon reports and build the Ryan report."
    )
    parser.add_argument("--config", default="execution/browser_config.json")
    parser.add_argument("--input-dir", default="")
    parser.add_argument("--existing-ryan", default="")
    parser.add_argument("--fresh-output", default="")
    parser.add_argument("--append-output", default="")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    # Derive defaults from the browser config's download directory.
    dl_dir = args.input_dir or _downloads_dir_from_config(
        str(repo_root / args.config)
    )
    if not dl_dir:
        dl_dir = os.path.expandvars("${HOME}/Downloads/ryan-moves-and-tests")

    input_dir = args.input_dir or dl_dir
    existing_ryan = args.existing_ryan or str(Path(dl_dir) / "2026 RYAN MOVES.csv")
    fresh_output = args.fresh_output or str(Path(dl_dir) / "generated-ryan-report-latest-new-only.csv")
    append_output = args.append_output or str(Path(dl_dir) / "append-ryan-report-latest.csv")

    if not args.skip_download:
        run(
            [_python_exe(), "execution/download_reports.py", "--config", args.config],
            repo_root,
        )

    run(
        [
            _python_exe(),
            "execution/build_ryan_report.py",
            "--input-dir",
            input_dir,
            "--output",
            fresh_output,
            "--append-to",
            existing_ryan,
            "--append-output",
            append_output,
            "--only-new-orders",
        ],
        repo_root,
    )


if __name__ == "__main__":
    main()
