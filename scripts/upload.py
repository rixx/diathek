# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "tqdm"]
# ///
"""Upload image files to diathek's /api/upload/ endpoint, one at a time.

Usage:
    uv run scripts/upload.py --url https://diathek.example.com --user alice PATH [PATH ...]

Paths may be individual files or directories. Directories are walked
non-recursively unless --recursive is given. The password is read from the
DIATHEK_PASSWORD env var if set, otherwise prompted.
"""

import argparse
import getpass
import mimetypes
import os
import sys
from pathlib import Path

import httpx
from tqdm import tqdm

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def collect_files(paths, recursive):
    out = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            walker = p.rglob("*") if recursive else p.iterdir()
            for entry in walker:
                if entry.is_file() and entry.suffix.lower() in IMAGE_SUFFIXES:
                    out.append(entry)
        else:
            print(f"skip: {p} not found", file=sys.stderr)
    return sorted(set(out), key=lambda path: path.name)


def login(client, base_url, username, password):
    client.get(f"{base_url}/login/").raise_for_status()
    token = client.cookies.get("csrftoken")
    if not token:
        raise SystemExit("no csrftoken cookie returned by /login/")
    resp = client.post(
        f"{base_url}/login/",
        data={
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": token,
            "next": "/",
        },
        headers={"Referer": f"{base_url}/login/"},
    )
    resp.raise_for_status()
    if "sessionid" not in client.cookies:
        raise SystemExit("login failed — check credentials")


def upload_one(client, base_url, path):
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as fh:
        return client.post(
            f"{base_url}/api/upload/",
            files={"files": (path.name, fh, mime)},
            headers={
                "X-CSRFToken": client.cookies.get("csrftoken") or "",
                "Referer": f"{base_url}/",
            },
        )


def main():
    ap = argparse.ArgumentParser(description="Upload images to diathek one at a time.")
    ap.add_argument(
        "--url", required=True, help="base URL, e.g. https://diathek.example.com"
    )
    ap.add_argument("--user", required=True)
    ap.add_argument("--recursive", "-r", action="store_true")
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    files = collect_files(args.paths, args.recursive)
    if not files:
        print("no files to upload", file=sys.stderr)
        return 1

    password = os.environ.get("DIATHEK_PASSWORD") or getpass.getpass(
        f"password for {args.user}: "
    )
    base = args.url.rstrip("/")

    with httpx.Client(timeout=300.0, follow_redirects=True) as client:
        login(client, base, args.user, password)
        errors = skipped = 0
        bar = tqdm(files, unit="file", desc="uploading")
        for path in bar:
            bar.set_postfix_str(path.name, refresh=False)
            resp = upload_one(client, base, path)
            if resp.status_code == 200:
                payload = resp.json()
                if payload["skipped"]:
                    skipped += 1
                    tqdm.write(f"skipped (duplicate): {path.name}")
            else:
                errors += 1
                try:
                    msg = resp.json().get("error", resp.text)
                except ValueError:
                    msg = resp.text
                tqdm.write(
                    f"ERROR {resp.status_code} {path.name}: {msg}", file=sys.stderr
                )
            bar.set_postfix(errors=errors, skipped=skipped, refresh=False)
        bar.close()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
