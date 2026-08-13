#!/bin/bash
# CPU print OCR for one harvested book job (historical-ocr / Tesseract).
# Use for Archive.org / Google Books printed editions — not manuscript HTR.
#
# Env:
#   JOB_ID    — required
#   JOBS_ROOT — default /ocean/projects/hum260002p/sstrickland/computus_htr_jobs
#
#SBATCH -J cwh-print
# Account QOS is GPU-only (no RM); Tesseract is CPU-bound but must land on GPU-shared.
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH --qos=gpu
#SBATCH --ntasks-per-node=4
#SBATCH -N 1
#SBATCH -t 12:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/computus_htr_jobs/logs/%x-%j.out
#SBATCH -e /ocean/projects/hum260002p/sstrickland/computus_htr_jobs/logs/%x-%j.err

set -euo pipefail

: "${JOB_ID:?JOB_ID required}"
JOBS_ROOT="${JOBS_ROOT:-/ocean/projects/hum260002p/sstrickland/computus_htr_jobs}"
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
HIST=/ocean/projects/hum260002p/sstrickland/historical-ocr
JOB="$JOBS_ROOT/$JOB_ID"
PAGES="$JOB/01_pages_2500"
ART="$JOB/03_artifacts_2500"
SRC_CHUNKS="$JOB/00_sources_chunks"

mkdir -p "$JOBS_ROOT/logs" "$PAGES" "$ART" "$JOB/logs" "$JOB/status"

export HISTORICAL_OCR_ROOT="$HIST"
export TRANSCRIBER_SHELL_ROOT="$SRC"
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"
# Bridges layout: package under .../src/; yaml specs under .../src/scripts/latin_ms/...
export TRANSCRIBER_SHELL_DOCUMENT_TYPES_DIR="${TRANSCRIBER_SHELL_DOCUMENT_TYPES_DIR:-$SRC/scripts/latin_ms/document_types}"
export TESSDATA_PREFIX="${TESSDATA_PREFIX:-$HIST/models/tessdata}"
export TRANSCRIBER_SHELL_LLM_MODE=off
export TRANSCRIBER_SHELL_HTR_COMBINATION=tesseract_htr
export TRANSCRIBER_SHELL_ARTIFACTS_DIR="$ART"
export TRANSCRIBER_SHELL_TESSERACT_ENABLED=1

# Prefer lat_pre1800, else histnews
if [[ -f "$HIST/models/lat_pre1800.traineddata" ]]; then
  export TRANSCRIBER_SHELL_TESSERACT_FINETUNE_PATH="$HIST/models/lat_pre1800.traineddata"
  export TRANSCRIBER_SHELL_TESSERACT_FINETUNE_LANG=lat_pre1800
elif [[ -f "$HIST/models/histnews.traineddata" ]]; then
  export TRANSCRIBER_SHELL_TESSERACT_FINETUNE_PATH="$HIST/models/histnews.traineddata"
  export TRANSCRIBER_SHELL_TESSERACT_FINETUNE_LANG=histnews
fi

# Use historical-ocr venv when present (pytesseract + deps)
if [[ -x "$HIST/.venv/bin/python" ]]; then
  PY="$HIST/.venv/bin/python"
else
  module load anaconda3 2>/dev/null || true
  # shellcheck disable=SC1091
  source "$SRC/scripts/bridges_kraken_activate.sh"
  PY=python3
fi

command -v tesseract >/dev/null || { echo "ERROR: tesseract missing on PATH" >&2; exit 1; }
tesseract --version | head -1

export JOB
"$PY" - <<'PY'
import os
from pathlib import Path
from PIL import Image

job = Path(os.environ["JOB"])
src = job / "00_sources_chunks"
pages = job / "01_pages_2500"
pages.mkdir(parents=True, exist_ok=True)
max_edge = 2500
n_new = 0
if src.is_dir():
    for p in sorted(src.rglob("*.jpg")):
        dest = pages / p.name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        with Image.open(p) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, max_edge / max(w, h))
            if scale < 1.0:
                im = im.resize((int(w * scale), int(h * scale)))
            tmp = dest.with_suffix(".tmp.jpg")
            im.save(tmp, "JPEG", quality=90)
            tmp.replace(dest)
        n_new += 1
print(f"staged_new={n_new} total={sum(1 for _ in pages.glob('*.jpg'))}")
PY

n_pages=$(find "$PAGES" -maxdepth 1 -name '*.jpg' | wc -l | tr -d ' ')
echo "JOB_ID=$JOB_ID pages=$n_pages finetune=${TRANSCRIBER_SHELL_TESSERACT_FINETUNE_PATH:-none}"
date -Iseconds > "$JOB/status/print_ocr_bridges.STARTED"

cd "$SRC"
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"
# Package has no __main__; invoke CLI module entrypoint.
"$PY" - <<PY 2>&1 | tee -a "$JOB/logs/bridges_print_ocr.log"
import sys
from transcriber_shell.cli import main

sys.argv = [
    "transcriber-shell",
    "batch",
    r"""$PAGES""",
    "--doc-type", "early_modern_latin",
    "--llm-mode", "off",
    "--htr-combination", "tesseract_htr",
    "--skip-successful",
    "--continue-on-lineation-failure",
    "--batch-report", r"""$JOB/logs/print_ocr_report.json""",
]
main()
PY

yaml_n=$(find "$ART" -name '*_transcription.yaml' 2>/dev/null | wc -l | tr -d ' ')
echo "yaml_pages=$yaml_n"
date -Iseconds > "$JOB/status/print_ocr_bridges.DONE"
echo "DONE $JOB_ID yaml=$yaml_n"
