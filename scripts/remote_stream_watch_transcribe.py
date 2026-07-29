#!/usr/bin/env python3
"""Watch a streaming manuscript acquisition and transcribe pages as they arrive."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

JOB = Path(os.environ["STREAM_JOB_DIR"]).expanduser()
SRC = JOB / "00_sources_chunks"
PAGES = JOB / os.environ.get("STREAM_PAGES_DIR", "01_pages_2500")
ART = JOB / os.environ.get("STREAM_ARTIFACTS_DIR", "03_artifacts_2500")
BATCHES = Path(os.environ.get("STREAM_BATCHES_DIR", str(JOB / "transcription_batches"))).expanduser()
LOG = JOB / "logs" / "watch_transcribe.log"

IMAGE_NAME_CONTAINS = os.environ.get("STREAM_IMAGE_NAME_CONTAINS", "")
MAX_LONG_EDGE = int(os.environ.get("STREAM_MAX_LONG_EDGE", "2500"))
BATCH_SIZE = int(os.environ.get("STREAM_BATCH_SIZE", "8"))
IDLE_LIMIT = int(os.environ.get("STREAM_IDLE_LIMIT", "30"))
DOC_TYPE = os.environ.get("STREAM_DOC_TYPE", "computus_medieval_latin")
PROVIDER = os.environ.get("STREAM_PROVIDER", "gemini")
HTR_COMBINATION = os.environ.get("STREAM_HTR_COMBINATION", "")
SKIP_LINES_XML_VALIDATION = os.environ.get("STREAM_SKIP_LINES_XML_VALIDATION", "")
TSHELL_ROOT = Path(os.environ.get("STREAM_TRANSCRIPTION_SHELL_ROOT", "~/Projects/transcription-shell")).expanduser()
TSHELL_VENV = Path(os.environ.get("STREAM_TRANSCRIPTION_SHELL_VENV", str(TSHELL_ROOT / ".venv-lineation"))).expanduser()


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def resize(src: Path, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return False
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, MAX_LONG_EDGE / max(w, h))
            if scale < 1.0:
                im = im.resize((int(w * scale), int(h * scale)))
            tmp = dest.with_suffix(".tmp.jpg")
            im.save(tmp, "JPEG", quality=90)
            tmp.replace(dest)
        return True
    except Exception as e:
        log(f"WARN resize failed {src}: {e}")
        return False


def stage_new() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in sorted(SRC.rglob("*.jpg")):
        if IMAGE_NAME_CONTAINS and IMAGE_NAME_CONTAINS not in src.name:
            continue
        dest = PAGES / src.name
        if resize(src, dest):
            count += 1
    return count


def valid_yaml(stem: str) -> bool:
    if (ART / stem / f"{stem}_transcription.yaml").exists():
        return True
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", stem)
    if sanitized != stem:
        sanitized_dir = ART / sanitized
        # yaml filename inside may use original stem or sanitized name
        if (sanitized_dir / f"{stem}_transcription.yaml").exists():
            return True
        if (sanitized_dir / f"{sanitized}_transcription.yaml").exists():
            return True
    return False


def pending_images() -> list[Path]:
    imgs: list[Path] = []
    for img in sorted(PAGES.glob("*.jpg")):
        if valid_yaml(img.stem):
            continue
        if (ART / img.stem / ".failed").exists():
            continue
        imgs.append(img)
    return imgs


def acquisition_running() -> bool:
    for pidfile in (JOB / "status").glob("acquire_*.pid"):
        try:
            os.kill(int(pidfile.read_text().strip()), 0)
            return True
        except Exception:
            pass
    return False


def run_batch(imgs: list[Path], idx: int) -> None:
    batch_dir = BATCHES / f"batch_{idx:04d}"
    if batch_dir.exists():
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True)
    for img in imgs:
        os.symlink(img, batch_dir / img.name)

    report = JOB / "logs" / f"transcription_batch_{idx:04d}.json"
    log_file = JOB / "logs" / f"transcription_batch_{idx:04d}.log"
    htr_export = f"export TRANSCRIBER_SHELL_HTR_COMBINATION='{HTR_COMBINATION}' && " if HTR_COMBINATION else ""
    skip_xml_export = f"export TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION='{SKIP_LINES_XML_VALIDATION}' && " if SKIP_LINES_XML_VALIDATION else ""
    cmd = (
        f"cd '{TSHELL_ROOT}' && "
        f"source '{TSHELL_VENV}/bin/activate' && "
        f"export PYTHONPATH='{TSHELL_ROOT}/src' && "
        f"export TRANSCRIBER_SHELL_ARTIFACTS_DIR='{ART}' && "
        f"{htr_export}"
        f"{skip_xml_export}"
        f"transcriber-shell batch '{batch_dir}' "
        f"--doc-type '{DOC_TYPE}' "
        f"--provider '{PROVIDER}' "
        "--skip-successful "
        "--continue-on-lineation-failure "
        f"--batch-report '{report}'"
    )
    log(f"RUN batch {idx} images={len(imgs)}")
    with log_file.open("w", encoding="utf-8") as f:
        result = subprocess.run(["bash", "-lc", cmd], stdout=f, stderr=subprocess.STDOUT)
    log(f"DONE batch {idx} exit={result.returncode}")
    if result.returncode != 0:
        for img in imgs:
            if not valid_yaml(img.stem):
                failed = ART / img.stem / ".failed"
                failed.parent.mkdir(parents=True, exist_ok=True)
                failed.write_text(f"batch {idx} exit {result.returncode}\n", encoding="utf-8")


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    BATCHES.mkdir(parents=True, exist_ok=True)
    log("watch_transcribe start")
    idle = 0
    batch_idx = 1
    while True:
        staged = stage_new()
        pending = pending_images()
        done = len(list(ART.rglob("*_transcription.yaml")))
        downloaded = len(list(PAGES.glob("*.jpg")))
        log(f"status staged_new={staged} downloaded={downloaded} done={done} pending={len(pending)}")
        if pending:
            idle = 0
            run_batch(pending[:BATCH_SIZE], batch_idx)
            batch_idx += 1
            continue
        if not acquisition_running():
            idle += 1
        if idle >= IDLE_LIMIT:
            log("watch_transcribe complete: acquisition idle and no pending images")
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
