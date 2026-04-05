from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], workdir: Path) -> None:
    completed = subprocess.run(cmd, cwd=workdir)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Axon reports and build the Ryan report."
    )
    parser.add_argument("--config", default="execution/browser_config.example.json")
    parser.add_argument("--input-dir", default="/Users/Naegele/Downloads")
    parser.add_argument(
        "--existing-ryan",
        default="/Users/Naegele/Downloads/ryan-moves-and-tests/2026 RYAN MOVES.csv",
    )
    parser.add_argument(
        "--fresh-output",
        default="/Users/Naegele/Downloads/generated-ryan-report-latest-new-only.csv",
    )
    parser.add_argument(
        "--append-output",
        default="/Users/Naegele/Downloads/append-ryan-report-latest.csv",
    )
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    if not args.skip_download:
        run(
            [sys.executable, "execution/download_reports.py", "--config", args.config],
            repo_root,
        )

    run(
        [
            sys.executable,
            "execution/build_ryan_report.py",
            "--input-dir",
            args.input_dir,
            "--output",
            args.fresh_output,
            "--append-to",
            args.existing_ryan,
            "--append-output",
            args.append_output,
            "--only-new-orders",
        ],
        repo_root,
    )


if __name__ == "__main__":
    main()
