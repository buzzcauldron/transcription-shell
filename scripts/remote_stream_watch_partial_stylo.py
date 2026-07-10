#!/usr/bin/env python3
"""Rebuild partial manuscript text and rerun R/stylo as transcriptions accumulate."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import yaml

JOB = Path(os.environ["STREAM_JOB_DIR"]).expanduser()
ART = JOB / os.environ.get("STREAM_ARTIFACTS_DIR", "03_artifacts_2500")
OUT = Path(os.environ["STREAM_STYLO_OUT"]).expanduser()
LOG = JOB / "logs" / "watch_partial_stylo.log"
SLUG = os.environ.get("STREAM_TARGET_SLUG", JOB.name)
TARGET = OUT / f"{SLUG}_partial_text.txt"
REF = Path(os.environ.get("STREAM_STYLO_REF", "~/Projects/stylometry-r/output/de_luce_r_rescore/reference_set_medieval_mixed")).expanduser()
RUNNER = Path(os.environ.get("STREAM_STYLO_RUNNER", "~/Projects/stylometry-r/scripts/run_stylo_target.R")).expanduser()
MIN_PAGES = int(os.environ.get("STREAM_STYLO_MIN_PAGES", "5"))
PAGE_STEP = int(os.environ.get("STREAM_STYLO_PAGE_STEP", "10"))
SLICE_SIZE = os.environ.get("STREAM_STYLO_SLICE_SIZE", "5000")
SLICE_OVERLAP = os.environ.get("STREAM_STYLO_SLICE_OVERLAP", "2500")


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def extract_text() -> tuple[str, int, int]:
    parts: list[str] = []
    pages = 0
    for ypath in sorted(ART.rglob("*_transcription.yaml")):
        try:
            data = yaml.safe_load(ypath.read_text(encoding="utf-8")) or {}
            segs = data.get("transcriptionOutput", {}).get("segments", [])
            texts: list[str] = []
            for seg in segs:
                if isinstance(seg, dict) and isinstance(seg.get("text"), str):
                    text = seg["text"]
                    text = re.sub(r"\[(?:illegible|unclear|gap|omitted)[^\]]*\]", " ", text, flags=re.I)
                    text = re.sub(r"<[^>]+>", " ", text)
                    texts.append(text.strip())
            page = " ".join(x for x in texts if x)
            if page:
                pages += 1
                parts.append(f"\n\n### {ypath.parent.name}\n{page}")
        except Exception as e:
            log(f"WARN read yaml {ypath}: {e}")
    full_text = "\n".join(parts).strip() + "\n" if parts else ""
    tokens = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", full_text))
    return full_text, pages, tokens


def any_pipeline_running() -> bool:
    self_pid = os.getpid()
    for pidfile in (JOB / "status").glob("*.pid"):
        try:
            pid = int(pidfile.read_text().strip())
            if pid == self_pid:
                continue
            os.kill(pid, 0)
            return True
        except Exception:
            pass
    return False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log("watch_partial_stylo start")
    last_pages = 0
    idle = 0
    while True:
        text, pages, tokens = extract_text()
        if pages >= MIN_PAGES and (last_pages == 0 or pages - last_pages >= PAGE_STEP):
            TARGET.write_text(text, encoding="utf-8")
            (OUT / f"{SLUG}_partial_metadata.json").write_text(
                json.dumps({"pages": pages, "tokens": tokens, "target_text": str(TARGET)}, indent=2),
                encoding="utf-8",
            )
            cmd = [
                "Rscript",
                str(RUNNER),
                str(TARGET),
                str(OUT),
                SLUG,
                str(REF),
                SLICE_SIZE,
                SLICE_OVERLAP,
            ]
            log(f"RUN stylo pages={pages} tokens={tokens}")
            with (JOB / "logs" / f"partial_stylo_{pages:04d}.log").open("w", encoding="utf-8") as f:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env={**os.environ, "R_LIBS_USER": os.environ.get("R_LIBS_USER", str(Path.home() / "Rlibs"))})
            last_pages = pages

        staged = len(list((JOB / os.environ.get("STREAM_PAGES_DIR", "01_pages_2500")).glob("*.jpg")))
        done = len(list(ART.rglob("*_transcription.yaml")))
        running = any_pipeline_running()
        log(f"status pages={pages} tokens={tokens} staged={staged} done={done} running={running}")
        if not running and staged <= done:
            idle += 1
        else:
            idle = 0
        if idle >= 20:
            log("watch_partial_stylo complete")
            break
        time.sleep(120)


if __name__ == "__main__":
    main()
