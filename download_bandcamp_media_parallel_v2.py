#!/usr/bin/env python3
"""
download_bandcamp_media_parallel_v2.py

Edited from your original par-el-el.py / download_bandcamp_previews_parallel.py.

What this does
--------------
Downloads Bandcamp preview MP3s in parallel, plus optional cover art.

It supports BOTH shapes:

Old featured-track JSON:
[
  {
    "rank": 1,
    "artist": "...",
    "album_or_record": "...",
    "featured_track_title": "...",
    "featured_track_mp3_128": "https://..."
  }
]

New manual/enriched JSON:
[
  {
    "rank": 9,
    "artist": "...",
    "album": "...",
    "title": "...",
    "audioFile": "bandcamp_preview_mp3s/example.mp3",
    "localImageUrl": "album-art/example.jpg",
    "remoteImageUrl": "https://...",
    "_download": {
      "mp3Url": "https://...",
      "imageUrl": "https://..."
    }
  }
]

Outputs
-------
- MP3 files
- cover art files, when URLs are available
- bandcamp_media_download_summary.json

Usage
-----
python3 download_bandcamp_media_parallel_v2.py \
  --input manual_adds_enriched.json

python3 download_bandcamp_media_parallel_v2.py \
  --input santa_fe_bandcamp_best_of_variety_featured_tracks.json \
  --audio-only
"""

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests


print_lock = threading.Lock()


def log(*args):
    with print_lock:
        print(*args, flush=True)


def slugify(value, max_length=90):
    value = str(value or "").strip().lower()
    value = re.sub(r"[’'“”\"`]", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return (value or "untitled")[:max_length].strip("-")


def human_bytes(num_bytes):
    try:
        num_bytes = float(num_bytes)
    except Exception:
        return "unknown size"

    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024

    return f"{num_bytes:.1f} TB"


def make_session(accept="*/*"):
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": accept,
        "Referer": "https://bandcamp.com/",
    })
    return session


def validate_url(url, expected_host_hint=None):
    if not url:
        return False, "Missing URL"

    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return False, f"Invalid URL scheme: {parsed.scheme}"

    if not parsed.netloc:
        return False, "URL has no host"

    if expected_host_hint and expected_host_hint not in parsed.netloc:
        return False, f"Unexpected host: {parsed.netloc}"

    return True, ""


def build_audio_filename(row):
    existing = row.get("audioFile")
    if existing:
        return Path(existing)

    rank = row.get("rank", "")
    try:
        rank_str = f"{int(rank):02d}"
    except Exception:
        rank_str = "xx"

    artist_slug = slugify(row.get("artist", "unknown-artist"), max_length=45)
    track_title = (
        row.get("featured_track_title")
        or row.get("trackTitle")
        or row.get("title")
        or row.get("album_or_record")
        or row.get("album")
        or "preview"
    )
    track_slug = slugify(track_title, max_length=60)

    return Path("bandcamp_preview_mp3s") / f"{rank_str}-{artist_slug}-{track_slug}.mp3"


def build_image_filename(row):
    existing = row.get("localImageUrl") or row.get("imageUrl")
    if existing and not str(existing).startswith("http"):
        return Path(existing)

    rank = row.get("rank", "")
    try:
        rank_str = f"{int(rank):02d}"
    except Exception:
        rank_str = "xx"

    artist_slug = slugify(row.get("artist", "unknown-artist"), max_length=45)
    album_slug = slugify(row.get("album") or row.get("album_or_record") or row.get("title") or "cover", max_length=60)

    return Path("album-art") / f"{rank_str}-{artist_slug}-{album_slug}.jpg"


def get_audio_url(row):
    download = row.get("_download") or {}
    return (
        download.get("mp3Url")
        or download.get("mp3")
        or row.get("featured_track_mp3_128")
        or row.get("mp3Url")
        or row.get("mp3_url")
    )


def get_image_url(row):
    download = row.get("_download") or {}
    return (
        download.get("imageUrl")
        or download.get("image")
        or row.get("remoteImageUrl")
        or row.get("primaryImageUrl")
        or row.get("image_url")
    )


def download_file(url, output_path, accept, timeout, overwrite=False):
    if output_path.exists() and output_path.stat().st_size > 0 and not overwrite:
        return {
            "status": "skipped",
            "reason": "File already exists",
            "output_path": str(output_path),
            "bytes": output_path.stat().st_size,
            "http_status": "",
            "content_type": "",
        }

    valid, reason = validate_url(url)
    if not valid:
        return {
            "status": "failed",
            "reason": reason,
            "output_path": str(output_path),
            "bytes": 0,
            "http_status": "",
            "content_type": "",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    max_attempts = 4
    backoff_seconds = 1.5

    for attempt in range(1, max_attempts + 1):
        session = make_session(accept=accept)

        try:
            log(f"    Attempt {attempt}/{max_attempts}: {url}")

            with session.get(url, stream=True, timeout=timeout) as response:
                status = response.status_code
                content_type = response.headers.get("content-type", "")

                if status != 200:
                    reason = f"HTTP {status}"
                    if status in {408, 429, 500, 502, 503, 504} and attempt < max_attempts:
                        sleep_for = backoff_seconds * attempt
                        log(f"    Retrying after {reason}; sleeping {sleep_for:.1f}s")
                        time.sleep(sleep_for)
                        continue

                    return {
                        "status": "failed",
                        "reason": reason,
                        "output_path": str(output_path),
                        "bytes": 0,
                        "http_status": status,
                        "content_type": content_type,
                    }

                temp_path = output_path.with_suffix(output_path.suffix + ".part")
                bytes_downloaded = 0

                with temp_path.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 64):
                        if not chunk:
                            continue
                        f.write(chunk)
                        bytes_downloaded += len(chunk)

                if bytes_downloaded == 0:
                    temp_path.unlink(missing_ok=True)
                    reason = "Downloaded 0 bytes"
                    if attempt < max_attempts:
                        time.sleep(backoff_seconds * attempt)
                        continue

                    return {
                        "status": "failed",
                        "reason": reason,
                        "output_path": str(output_path),
                        "bytes": 0,
                        "http_status": status,
                        "content_type": content_type,
                    }

                temp_path.replace(output_path)

                return {
                    "status": "downloaded",
                    "reason": "Downloaded successfully",
                    "output_path": str(output_path),
                    "bytes": bytes_downloaded,
                    "http_status": status,
                    "content_type": content_type,
                }

        except requests.RequestException as exc:
            reason = f"Request error: {exc}"
            output_path.with_suffix(output_path.suffix + ".part").unlink(missing_ok=True)

            if attempt < max_attempts:
                sleep_for = backoff_seconds * attempt
                log(f"    {reason}; retrying in {sleep_for:.1f}s")
                time.sleep(sleep_for)
                continue

            return {
                "status": "failed",
                "reason": reason,
                "output_path": str(output_path),
                "bytes": 0,
                "http_status": "",
                "content_type": "",
            }

    return {
        "status": "failed",
        "reason": "Unknown failure",
        "output_path": str(output_path),
        "bytes": 0,
        "http_status": "",
        "content_type": "",
    }


def build_jobs(rows, audio_only=False, cover_only=False):
    jobs = []

    for index, row in enumerate(rows, start=1):
        artist = row.get("artist", "Unknown Artist")
        title = row.get("featured_track_title") or row.get("trackTitle") or row.get("title") or row.get("album_or_record") or row.get("album")

        if not cover_only:
            audio_url = get_audio_url(row)
            jobs.append({
                "index": index,
                "kind": "audio",
                "artist": artist,
                "title": title,
                "url": audio_url,
                "output_path": build_audio_filename(row),
                "accept": "audio/mpeg,audio/*,*/*;q=0.8",
            })

        if not audio_only:
            image_url = get_image_url(row)
            if image_url:
                jobs.append({
                    "index": index,
                    "kind": "image",
                    "artist": artist,
                    "title": title,
                    "url": image_url,
                    "output_path": build_image_filename(row),
                    "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                })

    return jobs


def process_job(job, total_jobs, timeout, overwrite, stagger, max_workers):
    if stagger:
        time.sleep(stagger * (job["index"] % max_workers))

    log("-" * 72)
    log(f"[{job['index']}/{total_jobs}] {job['kind'].upper()}")
    log(f"  Artist: {job['artist']}")
    log(f"  Title:  {job['title']}")
    log(f"  Output: {job['output_path']}")

    result = download_file(
        url=job["url"],
        output_path=Path(job["output_path"]),
        accept=job["accept"],
        timeout=timeout,
        overwrite=overwrite,
    )

    result.update({
        "kind": job["kind"],
        "artist": job["artist"],
        "title": job["title"],
        "url": job["url"],
    })

    if result["status"] == "downloaded":
        log(f"✅ Downloaded {job['kind']}: {result['output_path']} ({human_bytes(result['bytes'])})")
    elif result["status"] == "skipped":
        log(f"↪️  Skipped {job['kind']}: {result['output_path']}")
    else:
        log(f"❌ Failed {job['kind']}: {result.get('reason')}")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="manual_adds_enriched.json")
    parser.add_argument("--summary-log", default="bandcamp_media_download_summary.json")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--stagger", type=float, default=0.15)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--audio-only", action="store_true")
    parser.add_argument("--cover-only", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Could not find input JSON: {input_path}")

    rows = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Expected JSON root to be a list.")

    jobs = build_jobs(
        rows,
        audio_only=args.audio_only,
        cover_only=args.cover_only,
    )

    total_jobs = len(jobs)
    log("=" * 72)
    log("Bandcamp Media Downloader — Parallel v2")
    log("=" * 72)
    log(f"Input JSON: {input_path}")
    log(f"Jobs:       {total_jobs}")
    log(f"Workers:    {args.workers}")
    log("=" * 72)

    results = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                process_job,
                job,
                total_jobs,
                args.timeout,
                args.overwrite,
                args.stagger,
                args.workers,
            )
            for job in jobs
        ]

        for future in as_completed(futures):
            results.append(future.result())

    downloaded = [r for r in results if r.get("status") == "downloaded"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    failed = [r for r in results if r.get("status") == "failed"]

    summary = {
        "input_json": str(input_path),
        "total_jobs": total_jobs,
        "downloaded_count": len(downloaded),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "all_results": results,
    }

    Path(args.summary_log).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log("=" * 72)
    log("Download summary")
    log("=" * 72)
    log(f"Downloaded: {len(downloaded)}")
    log(f"Skipped:    {len(skipped)}")
    log(f"Failed:     {len(failed)}")
    log(f"Summary:    {args.summary_log}")

    if failed:
        log("")
        log("Failures:")
        for item in failed:
            log(f"  - {item.get('kind')}: {item.get('artist')} — {item.get('title')} ({item.get('reason')})")

    log("=" * 72)


if __name__ == "__main__":
    main()
