#!/usr/bin/env python3
"""Per-manuscript acquire completion markers for the computus harvest.

Signals written:
  - <jobs>/<id>/status/acquire.DONE   JSON reason + image counts
  - <jobs>/<id>/status/acquire.FAILED when scrape exits with too few images
  - optional <harvest_root>/done/<id>  empty/symlink-level side index
  - <harvest_root>/done/index.jsonl    append-only log of DONE events

Downstream HTR may start as soon as acquire.DONE exists (do not wait for global harvest DONE).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2", ".webp"}
DONE_NAME = "acquire.DONE"
FAILED_NAME = "acquire.FAILED"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_images(path: Path) -> int:
    if not path.is_dir():
        return 0
    n = 0
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_SUFFIXES:
            n += 1
    return n


def acquire_running(job: Path) -> bool:
    """True if a live acquire_full.pid is present."""
    pid_path = job / "status" / "acquire_full.pid"
    if not pid_path.is_file():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sufficient(
    nimg: int,
    *,
    min_images: int,
    page_estimate: int | None = None,
) -> bool:
    if nimg < min_images:
        return False
    if page_estimate and page_estimate > 0:
        # Full (or near-full) codex pull — still allow early DONE if estimate wrong
        if nimg >= int(page_estimate * 0.9):
            return True
        # Scrape finished with less than estimate is still "done attempt"
        return True  # caller gates on process exit for incomplete estimates
    return True


def write_marker(
    job: Path,
    *,
    ok: bool,
    payload: dict[str, Any],
    harvest_root: Path | None = None,
) -> Path:
    status = job / "status"
    status.mkdir(parents=True, exist_ok=True)
    name = DONE_NAME if ok else FAILED_NAME
    path = status / name
    body = dict(payload)
    body.setdefault("written_at", now_iso())
    body.setdefault("job_id", job.name)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # remove opposite marker
    other = status / (FAILED_NAME if ok else DONE_NAME)
    if other.exists():
        try:
            other.unlink()
        except OSError:
            pass
    if ok and harvest_root is not None:
        ddir = harvest_root / "done"
        ddir.mkdir(parents=True, exist_ok=True)
        side = ddir / job.name
        side.write_text(json.dumps(body, ensure_ascii=False) + "\n", encoding="utf-8")
        idx = ddir / "index.jsonl"
        with idx.open("a", encoding="utf-8") as f:
            f.write(json.dumps(body, ensure_ascii=False) + "\n")
    return path


def mark_done(
    job: Path,
    *,
    nimg: int,
    reason: str,
    min_images: int = 5,
    page_estimate: int | None = None,
    returncode: int | None = None,
    host: str | None = None,
    harvest_root: Path | None = None,
    force: bool = False,
) -> Path | None:
    """Mark manuscript acquire complete if criteria met (or force)."""
    if not force and nimg < min_images:
        return None
    if not force and page_estimate and page_estimate > 0:
        # If still running we never call mark_done; on exit allow partial with min_images
        pass
    payload = {
        "status": "done",
        "reason": reason,
        "n_images": nimg,
        "min_images": min_images,
        "page_estimate": page_estimate,
        "returncode": returncode,
        "host": host,
    }
    return write_marker(job, ok=True, payload=payload, harvest_root=harvest_root)


def mark_failed(
    job: Path,
    *,
    nimg: int,
    reason: str,
    returncode: int | None = None,
    host: str | None = None,
    harvest_root: Path | None = None,
    min_images: int = 5,
    page_estimate: int | None = None,
) -> Path:
    payload = {
        "status": "failed",
        "reason": reason,
        "n_images": nimg,
        "min_images": min_images,
        "page_estimate": page_estimate,
        "returncode": returncode,
        "host": host,
    }
    return write_marker(job, ok=False, payload=payload, harvest_root=harvest_root)


def is_done(job: Path) -> bool:
    return (job / "status" / DONE_NAME).is_file()


def finalize_after_acquire(
    job: Path,
    *,
    returncode: int,
    min_images: int = 5,
    page_estimate: int | None = None,
    host: str | None = None,
    harvest_root: Path | None = None,
) -> str:
    """Called when strigil exits. Returns 'done'|'failed'|'partial'."""
    img = job / "00_sources_chunks" / "full"
    nimg = count_images(img)
    # clear pid file
    pidf = job / "status" / "acquire_full.pid"
    if pidf.exists():
        try:
            pidf.unlink()
        except OSError:
            pass
    if nimg >= min_images:
        mark_done(
            job,
            nimg=nimg,
            reason="strigil_exit",
            min_images=min_images,
            page_estimate=page_estimate,
            returncode=returncode,
            host=host,
            harvest_root=harvest_root,
        )
        return "done"
    mark_failed(
        job,
        nimg=nimg,
        reason="strigil_exit_insufficient_images",
        returncode=returncode,
        host=host,
        harvest_root=harvest_root,
        min_images=min_images,
        page_estimate=page_estimate,
    )
    return "failed"
