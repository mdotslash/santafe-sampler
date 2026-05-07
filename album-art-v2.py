#!/usr/bin/env python3
"""
download_album_art_v2.py

Downloads Bandcamp cover art from either:
- album_art_manifest.json
- santa_fe_sampler_v2_curated.json
- metadata-style JSON exports

Supports these field names:
- remoteImageUrl
- image_url
- primaryImageUrl
- localImagePath
- localImageUrl
- imageUrl

Run:
    python3 -m pip install requests
    python3 download_album_art_v2.py

Optional:
    python3 download_album_art_v2.py santa_fe_sampler_v2_curated.json
"""

import json
import sys
import time
from pathlib import Path

import requests

INPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("album_art_manifest_v2.json")
OUTPUT_DIR = Path("album-art")
DELAY_SECONDS = 0.25
TIMEOUT_SECONDS = 30
SKIP_EXISTING = True

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Referer": "https://bandcamp.com/",
})


def get_remote_url(row):
    return (
        row.get("remoteImageUrl")
        or row.get("primaryImageUrl")
        or row.get("image_url")
    )


def get_local_path(row):
    local = (
        row.get("localImagePath")
        or row.get("localImageUrl")
        or row.get("imageUrl")
    )

    if not local:
        return None

    # If imageUrl is remote, don't use it as a local path.
    if str(local).startswith("http://") or str(local).startswith("https://"):
        return None

    return Path(local)


def is_bad_placeholder(url):
    if not url:
        return True

    bad_bits = [
        "a0_10.jpg",
        "None",
        "null",
    ]

    return any(bit in url for bit in bad_bits)


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing {INPUT}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = json.loads(INPUT.read_text(encoding="utf-8"))

    if not isinstance(rows, list):
        raise ValueError("Expected JSON root to be a list.")

    downloaded = 0
    skipped = 0
    failed = []

    print(f"Album art rows: {len(rows)}")
    print(f"Input:          {INPUT}")
    print(f"Output dir:     {OUTPUT_DIR}")
    print("-" * 72)

    for i, row in enumerate(rows, 1):
        url = get_remote_url(row)
        local = get_local_path(row)

        label = f"Rank {row.get('rank')}: {row.get('artist')} — {row.get('album') or row.get('album_or_record')}"
        print(f"[{i}/{len(rows)}] {label}")

        if is_bad_placeholder(url):
            reason = f"missing or placeholder remote image URL: {url}"
            print(f"  FAIL: {reason}")
            failed.append({**row, "reason": reason})
            continue

        if local is None:
            reason = "missing local image path field"
            print(f"  FAIL: {reason}")
            failed.append({**row, "reason": reason})
            continue

        if local.exists() and SKIP_EXISTING:
            print(f"  SKIP: exists: {local}")
            skipped += 1
            continue

        local.parent.mkdir(parents=True, exist_ok=True)

        try:
            response = session.get(url, timeout=TIMEOUT_SECONDS)
            content_type = response.headers.get("content-type", "unknown")
            print(f"  HTTP: {response.status_code} | {content_type}")

            if response.status_code != 200:
                failed.append({**row, "reason": f"HTTP {response.status_code}"})
                print("  FAIL")
                continue

            if not content_type.startswith("image/"):
                failed.append({**row, "reason": f"not an image: {content_type}"})
                print("  FAIL: response was not an image")
                continue

            local.write_bytes(response.content)
            print(f"  SAVED: {local} ({len(response.content)} bytes)")
            downloaded += 1

        except requests.RequestException as exc:
            print(f"  FAIL: {exc}")
            failed.append({**row, "reason": str(exc)})

        time.sleep(DELAY_SECONDS)
        print("-" * 72)

    summary = {
        "input": str(INPUT),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed_count": len(failed),
        "failed": failed,
    }

    Path("album_art_download_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("Done.")
    print(f"Downloaded: {downloaded}")
    print(f"Skipped:    {skipped}")
    print(f"Failed:     {len(failed)}")
    print("Summary:    album_art_download_summary.json")


if __name__ == "__main__":
    main()