#!/bin/bash
# GPU HTR for one non-computus control miscellany (kraken only; no Gemini on Bridges).
#
# Env:
#   JOB_ID    — required (job directory name under JOBS_ROOT)
#   JOBS_ROOT — default /ocean/projects/hum260002p/sstrickland/control_miscellany_htr_jobs
#
#SBATCH -J ctrl-htr
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH --ntasks-per-node=4
#SBATCH -N 1
#SBATCH -t 24:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/control_miscellany_htr_jobs/logs/%x-%j.out
#SBATCH -e /ocean/projects/hum260002p/sstrickland/control_miscellany_htr_jobs/logs/%x-%j.err

set -euo pipefail

: "${JOB_ID:?JOB_ID required}"
JOBS_ROOT="${JOBS_ROOT:-/ocean/projects/hum260002p/sstrickland/control_miscellany_htr_jobs}"
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
JOB="$JOBS_ROOT/$JOB_ID"
PAGES="$JOB/01_pages_2500"
ART="$JOB/03_artifacts_2500"
SRC_CHUNKS="$JOB/00_sources_chunks"

mkdir -p "$JOBS_ROOT/logs" "$PAGES" "$ART" "$JOB/logs" "$JOB/status"

module load anaconda3 2>/dev/null || true
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
bash "$SRC/scripts/bridges_fix_kraken_numpy.sh" 2>/dev/null || true

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"
export TRANSCRIBER_SHELL_DOCUMENT_TYPES_DIR="${TRANSCRIBER_SHELL_DOCUMENT_TYPES_DIR:-$SRC/scripts/latin_ms/document_types}"
export TRANSCRIBER_SHELL_AUTO_EFFICIENCY=1
export TRANSCRIBER_SHELL_LLM_MODE=off
export TRANSCRIBER_SHELL_HTR_COMBINATION=kraken_htr
export TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken
export TRANSCRIBER_SHELL_REUSE_LINES_XML=true
export TRANSCRIBER_SHELL_ARTIFACTS_DIR="$ART"
# Non-computus Latin: r5, not computus/r7.
export TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH="${TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH:-$SRC/gm-htr-r5-best.mlmodel}"
export TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH="${TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/latin-ms-workspace/training/kraken_seg_updated_best.mlmodel}"

if [[ ! -f "$TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH" ]]; then
  echo "ERROR: missing HTR model $TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH" >&2
  exit 1
fi
if [[ ! -d "$SRC_CHUNKS" ]] && [[ ! -d "$PAGES" ]]; then
  echo "ERROR: no images under $JOB (need 00_sources_chunks or 01_pages_2500)" >&2
  exit 1
fi

export JOB
python3 - <<'PY'
import os
from pathlib import Path
from PIL import Image

job = Path(os.environ["JOB"])
src = job / "00_sources_chunks"
pages = job / "01_pages_2500"
pages.mkdir(parents=True, exist_ok=True)
max_edge = 2500
n_new = 0
if not src.is_dir():
    print(f"pages already staged: {sum(1 for _ in pages.glob('*.jpg'))}")
else:
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
echo "JOB_ID=$JOB_ID pages=$n_pages htr=$TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH"
date -Iseconds > "$JOB/status/htr_bridges.STARTED"

cd "$SRC"
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<PY 2>&1 | tee -a "$JOB/logs/bridges_htr.log"
import sys
from transcriber_shell.cli import main

sys.argv = [
    "transcriber-shell",
    "batch",
    r"""$PAGES""",
    "--doc-type", "medieval_latin_miscellany",
    "--llm-mode", "off",
    "--htr-combination", "kraken_htr",
    "--lineation-backend", "kraken",
    "--skip-successful",
    "--continue-on-lineation-failure",
    "--batch-report", r"""$JOB/logs/transcription_report.json""",
]
main()
PY

yaml_n=$(find "$ART" -name '*_transcription.yaml' 2>/dev/null | wc -l | tr -d ' ')
echo "yaml_pages=$yaml_n"
date -Iseconds > "$JOB/status/htr_bridges.DONE"
echo "DONE $JOB_ID yaml=$yaml_n"
