# Sampler v2 step-by-step scripts

These scripts split the rebuild into four easier-to-debug steps.

Copy all four scripts into your site folder, next to `index.html`.

## Setup

```bash
python3 -m pip install requests
ffmpeg -version
```

## Step 1 — Enrich JSON and create new playlist

```bash
python3 1_enrich_playlist.py --snippet-seconds 15 --interactive
```

Outputs:

```text
manual_adds_enriched.json
santa_fe_sampler_v2_curated.json
```

## Step 2 — Download new media

```bash
python3 2_download_new_media.py
```

This uses visible `curl` commands and downloads:

```text
bandcamp_preview_mp3s/
album-art/
```

## Step 3 — Render and encode mix

```bash
python3 3_render_encode_mix.py
```

Outputs:

```text
BANDCAMP_BEST_OF_SNIPPET_MIX.wav
BANDCAMP_BEST_OF_SNIPPET_MIX.mp3
BANDCAMP_BEST_OF_SNIPPET_MIX.webm
```

## Step 4 — Patch index.html

```bash
python3 4_patch_index.py
```

This backs up your current file to:

```text
index.before-v2.html
```

Then patches:

```text
index.html
```

## Test locally

```bash
python3 -m http.server 8000
```

Open:

```text
http://localhost:8000
```

## Commit

```bash
find . -name ".DS_Store" -delete
git status
git add index.html index.before-v2.html manual_adds_enriched.json santa_fe_sampler_v2_curated.json
git add BANDCAMP_BEST_OF_SNIPPET_MIX.wav BANDCAMP_BEST_OF_SNIPPET_MIX.mp3 BANDCAMP_BEST_OF_SNIPPET_MIX.webm
git add album-art bandcamp_preview_mp3s
git commit -m "Update sampler track list"
git push
```
