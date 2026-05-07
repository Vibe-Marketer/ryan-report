"""Daily folder-watcher pipeline: scan a source folder for fresh Axon
exports, build the Ryan-format new rows, append them to the canonical xlsx
as new printable section(s), and archive the source files by date.

Designed to be run on a daily schedule. Idempotent — if no fresh source files
are present, exits cleanly without touching anything.

Pipeline per run::

    1. Scan SOURCE_DIR for the most recent 'New RYAN*.csv' and
       'Order Master Report*.csv' (and 'audit info*.csv' if present).
    2. If both required files are present, run build_ryan_report.py against
       them with --historical-ryan pointed at the canonical xlsx (so the
       equipment-list lookup pulls in every year's serials).
    3. Run append_to_xlsx.py to add the generated rows as new section(s) at
       the bottom of the xlsx — wrapped at 25 lines per section.
    4. Move the processed source files into a dated archive folder.

Defaults match the layout we agreed on::

    Source folder:   ~/Downloads/ryan-moves-and-tests
    Canonical xlsx:  ~/Downloads/2026 RYAN MOVES.xlsx
    Archive root:    ~/Downloads/ryan-archive/<YYYY-MM-DD>/

Usage::

    python execution/run_daily_append.py            # full run
    python execution/run_daily_append.py --dry-run  # report only, no changes
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

def _resolve_downloads_dir() -> Path:
    """Find the user's Downloads folder, whether we're running on their Mac
    directly or inside Cowork's sandbox.

    The sandbox mounts the user's Downloads at
    `/sessions/<session-id>/mnt/Downloads`, while a normal Mac shell sees it
    at `~/Downloads`. Try both — first whichever resolves to an existing
    directory wins.
    """
    home_downloads = Path("~/Downloads").expanduser()
    if home_downloads.is_dir():
        return home_downloads
    sessions_root = Path("/sessions")
    if sessions_root.is_dir():
        try:
            session_dirs = list(sessions_root.iterdir())
        except PermissionError:
            session_dirs = []
        for session in session_dirs:
            mounted = session / "mnt" / "Downloads"
            try:
                if mounted.is_dir():
                    return mounted
            except PermissionError:
                continue
    # Fall back to the home path even if missing — caller surfaces the error.
    return home_downloads


_DOWNLOADS = _resolve_downloads_dir()
DEFAULT_SOURCE_DIR = _DOWNLOADS / "ryan-moves-and-tests"
DEFAULT_XLSX = _DOWNLOADS / "2026 RYAN MOVES.xlsx"
DEFAULT_ARCHIVE_ROOT = _DOWNLOADS / "ryan-archive"

REQUIRED_PREFIXES = ("New RYAN", "Order Master Report")
OPTIONAL_PREFIXES = ("audit info",)
SOURCE_SUFFIXES = (".csv", ".xlsx")


def _python() -> str:
    """Use the same interpreter that's running this script."""
    return sys.executable


def find_latest(source: Path, prefix: str) -> Path | None:
    """Most-recently-modified file in source dir matching prefix*.{csv,xlsx}."""
    matches: list[Path] = []
    for suffix in SOURCE_SUFFIXES:
        matches.extend(source.glob(f"{prefix}*{suffix}"))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def archive_files(files: list[Path], archive_root: Path, run_date: str) -> Path:
    """Move source files into archive_root/<run_date>/, returning that dir."""
    target = archive_root / run_date
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f and f.exists():
            destination = target / f.name
            # Avoid clobber if same-named archive already exists
            if destination.exists():
                stamp = datetime.datetime.now().strftime("%H%M%S")
                destination = target / f"{destination.stem}.{stamp}{destination.suffix}"
            shutil.move(str(f), str(destination))
    return target


def run_subprocess(cmd: list[str], cwd: Path) -> int:
    """Run a child process, streaming stdout/stderr live. Returns exit code."""
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX))
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen but don't modify the xlsx or move files.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Run the pipeline but leave source files in place (useful for testing).",
    )
    args = parser.parse_args()

    source = Path(args.source_dir).expanduser()
    xlsx = Path(args.xlsx).expanduser()
    archive_root = Path(args.archive_root).expanduser()
    repo_root = Path(__file__).resolve().parents[1]

    print(f"Source folder:   {source}")
    print(f"Canonical xlsx:  {xlsx}")
    print(f"Archive root:    {archive_root}")
    print(f"Dry run:         {args.dry_run}")

    if not source.exists():
        print(f"ERROR: Source folder does not exist: {source}")
        return 1
    if not xlsx.exists():
        print(f"ERROR: Canonical xlsx does not exist: {xlsx}")
        return 1

    new_ryan = find_latest(source, "New RYAN")
    order_master = find_latest(source, "Order Master Report")
    audit_info = find_latest(source, "audit info")

    print(f"\nLatest files in source folder:")
    print(f"  New RYAN:            {new_ryan or '(missing)'}")
    print(f"  Order Master Report: {order_master or '(missing)'}")
    print(f"  audit info (opt):    {audit_info or '(missing)'}")

    if not new_ryan or not order_master:
        print(
            "\nNothing to do — required source files are missing. "
            "Run the desktop app to download fresh exports, then re-run this."
        )
        return 0

    # Lock-file guard: refuse to run if Excel has the xlsx open.
    lock = xlsx.parent / f"~${xlsx.name}"
    if lock.exists():
        print(
            f"\nERROR: Excel currently has '{xlsx.name}' open ({lock.name} present). "
            f"Close the workbook in Excel and re-run."
        )
        return 1

    fresh_output = source / "generated-ryan-report-new-only.csv"

    if args.dry_run:
        print("\nDry run — would:")
        print(f"  1. Run build_ryan_report.py --input-dir {source} \\")
        print(f"     --output {fresh_output} \\")
        print(f"     --historical-ryan {xlsx}")
        print(f"  2. Run append_to_xlsx.py --xlsx {xlsx} --from-csv {fresh_output}")
        print(f"  3. Move source files into {archive_root}/<today>/")
        return 0

    # 1. Build the new-only CSV
    build_cmd = [
        _python(),
        str(repo_root / "execution" / "build_ryan_report.py"),
        "--input-dir", str(source),
        "--output", str(fresh_output),
        "--historical-ryan", str(xlsx),
    ]
    print(f"\nStep 1/3: Build new-only CSV")
    print(f"  Command: {' '.join(build_cmd)}")
    rc = run_subprocess(build_cmd, repo_root)
    if rc != 0:
        print(f"  Build failed (exit {rc}); leaving source files in place.")
        return rc

    # 2. Append to xlsx (writes a JSON summary describing what happened)
    summary_path = source / "completion-summary.json"
    append_cmd = [
        _python(),
        str(repo_root / "execution" / "append_to_xlsx.py"),
        "--xlsx", str(xlsx),
        "--from-csv", str(fresh_output),
        "--summary-out", str(summary_path),
    ]
    print(f"\nStep 2/3: Append new rows as section(s) in {xlsx.name}")
    print(f"  Command: {' '.join(append_cmd)}")
    rc = run_subprocess(append_cmd, repo_root)
    if rc != 0:
        print(f"  Append failed (exit {rc}); leaving source files in place.")
        return rc

    # Surface the completion summary so the calling task (or wrapper) can
    # use it to drive an email draft for any sections that hit 25 rows.
    if summary_path.exists():
        try:
            import json as _json
            summary_data = _json.loads(summary_path.read_text())
            done = summary_data.get("completed_sections", [])
            if done:
                print(
                    f"\n  >> SECTIONS_COMPLETED_THIS_RUN: {len(done)}  "
                    f"page numbers: {[s['page_number'] for s in done]}"
                )
                print(f"  Summary file: {summary_path}")
            else:
                print("\n  No sections hit 25 rows this run — no email draft needed.")
        except Exception as exc:
            print(f"  Could not read summary JSON: {exc}")

    # 3. Archive
    if args.no_archive:
        print(f"\nStep 3/3: Skipped archive (--no-archive). Source files remain in place.")
        return 0

    files_to_archive: list[Path] = [f for f in (new_ryan, order_master, audit_info) if f]
    run_date = datetime.date.today().isoformat()
    print(f"\nStep 3/3: Archive source files to {archive_root / run_date}")
    archived_dir = archive_files(files_to_archive, archive_root, run_date)
    print(f"  Archived {len(files_to_archive)} files to {archived_dir}")

    # Also tuck the generated 'new-only' CSV and the run-summary JSON into the
    # archive so each daily run has a self-contained record of what got appended.
    for extra in (fresh_output, summary_path):
        if extra.exists():
            try:
                shutil.move(str(extra), str(archived_dir / extra.name))
                print(f"  Archived: {extra.name}")
            except Exception as exc:
                print(f"  Could not archive {extra.name} ({exc}) — left in source dir.")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
