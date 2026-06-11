#!/usr/bin/env python3
"""Catom support-ticket inbox.

Every time a client clicks "Report Issue" in Catom, a diagnostic bundle
(last run inputs + outputs, Distribution PDF, log tail, redacted config, their
message) is uploaded to the R2 bucket under feedback/. This tool lets Andrew
see and pull those tickets.

Usage:
    python3 tools/catom-tickets.py list                 # list all tickets, newest first
    python3 tools/catom-tickets.py get <key|latest>     # download + unzip a ticket
    python3 tools/catom-tickets.py show <key|latest>    # just print the user's message

Credentials are read from the same R2 env the CI uses, falling back to the
known account keys (account-scoped, same as callvault-assets).
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

import boto3
from botocore.client import Config

ENDPOINT = os.environ.get("R2_ENDPOINT_URL", "https://e9319ad5ca87e4768e7a79f1339ec8c8.r2.cloudflarestorage.com")
KEY      = os.environ.get("R2_ACCESS_KEY_ID", "a9e5b203af1862b9c1cbb936c6a0870d")
SECRET   = os.environ.get("R2_SECRET_ACCESS_KEY", "3e9e8e9e3bfd072a97ab57b4491902b44353308d247edd752c6489f0eebe19b9")
BUCKET   = os.environ.get("R2_BUCKET", "catom-updates")
PREFIX   = "feedback/"
OUTDIR   = Path.home() / "Downloads" / "catom-tickets"


def _s3():
    return boto3.client(
        "s3", endpoint_url=ENDPOINT,
        aws_access_key_id=KEY, aws_secret_access_key=SECRET,
        config=Config(signature_version="s3v4"), region_name="auto",
    )


def _all_tickets(s3):
    items = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX).get("Contents", [])
    return sorted(items, key=lambda x: x["LastModified"], reverse=True)


def _resolve(s3, key: str) -> str:
    if key == "latest":
        t = _all_tickets(s3)
        if not t:
            sys.exit("No tickets yet.")
        return t[0]["Key"]
    return key if key.startswith(PREFIX) else PREFIX + key


def cmd_list(s3):
    tickets = _all_tickets(s3)
    if not tickets:
        print("No tickets yet. (feedback/ is empty)")
        return
    print(f"{len(tickets)} ticket(s):\n")
    for o in tickets:
        # peek the user message
        msg = ""
        try:
            body = s3.get_object(Bucket=BUCKET, Key=o["Key"])["Body"].read()
            import io
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                if "feedback.txt" in z.namelist():
                    txt = z.read("feedback.txt").decode(errors="replace")
                    msg = txt.split("User message:", 1)[-1].strip().replace("\n", " ")[:90]
        except Exception:
            pass
        print(f"  {o['LastModified']:%Y-%m-%d %H:%M}  {o['Size']//1024:>5} KB  {o['Key'].split('/')[-1]}")
        if msg:
            print(f"      “{msg}”")


def cmd_show(s3, key):
    import io
    k = _resolve(s3, key)
    body = s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        for name in ("feedback.txt", "feedback.json"):
            if name in z.namelist():
                print(f"--- {name} ---")
                print(z.read(name).decode(errors="replace"))


def cmd_get(s3, key):
    k = _resolve(s3, key)
    name = k.split("/")[-1]
    OUTDIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTDIR / name
    s3.download_file(BUCKET, k, str(zip_path))
    unzip_dir = OUTDIR / name.replace(".zip", "")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(unzip_dir)
    print(f"Downloaded + unzipped to:\n  {unzip_dir}")
    print("\nContents:")
    for p in sorted(unzip_dir.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(unzip_dir)}  ({p.stat().st_size} B)")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "get", "show"):
        print(__doc__)
        sys.exit(1)
    s3 = _s3()
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list(s3)
    elif cmd == "show":
        cmd_show(s3, sys.argv[2] if len(sys.argv) > 2 else "latest")
    elif cmd == "get":
        cmd_get(s3, sys.argv[2] if len(sys.argv) > 2 else "latest")


if __name__ == "__main__":
    main()
