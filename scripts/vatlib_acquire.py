#!/usr/bin/env python3
"""Download IIIF manuscript images with correct filenames.

Supports IIIF Presentation API v2 and v3 manifests.

Usage:
    python3 vatlib_acquire.py <manifest_url> <out_dir> [--workers N] [--skip-existing]
"""
import argparse
import sys
import urllib.request
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse


def fetch_manifest(url):
    req = urllib.request.Request(url, headers={"User-Agent": "strigil/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _stem_from_id(id_str):
    """Extract a clean filename stem from a IIIF service/resource @id."""
    path = urlparse(id_str).path.rstrip("/")
    # For IIIF image URLs like /loris/…/file.jp2/full/full/0/default/jpg,
    # walk backwards past IIIF path components to find the filename.
    parts = path.split("/")
    for part in reversed(parts):
        if part and not part.startswith("{") and "/" not in part:
            stem = part
            for suffix in (".jp2", ".JP2", ".jpg", ".JPG", ".tif", ".tiff", ".png"):
                if stem.lower().endswith(suffix.lower()):
                    stem = stem[: -len(suffix)]
                    break
            # Skip IIIF path components (full, max, 0, default, native, jpg, etc.)
            iiif_tokens = {"full", "max", "native", "0", "default", "jpg", "png", "native.jpg"}
            if stem.lower() in iiif_tokens or (stem.isdigit() and len(stem) <= 4):
                continue
            return stem
    return parts[-1] if parts else "image"


def canvas_image_url_and_name_v2(canvas):
    """Return (download_url, stem) from a IIIF v2 canvas, or None."""
    imgs = canvas.get("images") or []
    if not imgs:
        return None
    resource = imgs[0].get("resource", {})
    resource_id = resource.get("@id", "")
    svc = resource.get("service", {})
    svc_id = svc.get("@id", "") if isinstance(svc, dict) else ""

    # If resource @id is already a complete IIIF image URL, use it directly.
    # e-codices provides /full/full/0/default/jpg — non-standard but working.
    if resource_id and any(tok in resource_id for tok in ("/full/", "/native")):
        base = svc_id or resource_id
        return resource_id, _stem_from_id(base)

    # Construct from service @id
    base = svc_id or resource_id
    if not base:
        return None
    url = base.rstrip("/") + "/full/max/0/default.jpg"
    return url, _stem_from_id(base)


def canvas_image_url_and_name_v3(canvas):
    """Return (download_url, stem) from a IIIF v3 canvas, or None."""
    ann_page = (canvas.get("items") or [{}])[0]
    ann = (ann_page.get("items") or [{}])[0]
    body = ann.get("body")
    if isinstance(body, list):
        body = body[0] if body else {}
    if not body:
        return None

    body_id = body.get("id", "")
    svc_list = body.get("service", [])
    if not isinstance(svc_list, list):
        svc_list = [svc_list]

    svc_id = ""
    for s in svc_list:
        candidate = (s.get("@id") or s.get("id") or "").strip()
        if candidate:
            svc_id = candidate
            break

    if svc_id:
        url = svc_id.rstrip("/") + "/full/max/0/default.jpg"
        return url, _stem_from_id(svc_id)
    elif body_id:
        return body_id, _stem_from_id(body_id)
    return None


def download_one(url, dest, skip_existing):
    if skip_existing and dest.exists():
        return dest.name, "skip"
    req = urllib.request.Request(url, headers={"User-Agent": "strigil/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        dest.write_bytes(data)
        return dest.name, len(data)
    except Exception as e:
        return dest.name, f"ERR {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest_url")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"fetching manifest: {args.manifest_url}", flush=True)
    m = fetch_manifest(args.manifest_url)

    if "sequences" in m:
        canvases = m["sequences"][0].get("canvases", [])
        get_url_name = canvas_image_url_and_name_v2
        version = "v2"
    elif "items" in m and isinstance(m["items"], list) and m["items"] and isinstance(m["items"][0], dict):
        canvases = m["items"]
        get_url_name = canvas_image_url_and_name_v3
        version = "v3"
    else:
        canvases = []
        get_url_name = canvas_image_url_and_name_v2
        version = "unknown"

    print(f"manifest {version}, canvases: {len(canvases)}", flush=True)

    tasks = []
    for i, c in enumerate(canvases, 1):
        result = get_url_name(c)
        if result is None:
            print(f"[{i}] no image url", flush=True)
            continue
        url, stem = result
        dest = args.out_dir / f"{stem}.jpg"
        tasks.append((i, url, dest))

    done = skipped = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(download_one, url, dest, args.skip_existing): (i, url)
                for i, url, dest in tasks}
        for fut in as_completed(futs):
            i, url = futs[fut]
            name, result = fut.result()
            if result == "skip":
                skipped += 1
            elif isinstance(result, int):
                done += 1
                print(f"[{i}/{len(tasks)}] OK {name} ({result // 1024}k)", flush=True)
            else:
                failed += 1
                print(f"[{i}/{len(tasks)}] FAIL {name}: {result}", flush=True)

    print(f"\ndone: {done} downloaded, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
