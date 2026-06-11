#!/bin/bash
#SBATCH -J ibooks-pre1800
#SBATCH -p GPU-shared
#SBATCH --qos=gpu
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --cpus-per-task=5
#SBATCH -t 12:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/ibooks-pre1800-%j.out
# Filter Institutional Books 1.0 for pre-1800 Latin LLM corpus (metadata + optional OCR text).
set -euo pipefail

SHELL_ROOT="${TRANSCRIBER_SHELL_ROOT:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
OUT_DIR="${INST_BOOKS_OUT:-$SHELL_ROOT/institutional-books-pre1800-lat}"
PROFILE="${INST_BOOKS_PROFILE:-pre1800_latin_llm}"
EXPORT_TEXT="${INST_BOOKS_EXPORT_TEXT:-0}"
EXPORT_TEXT_ONLY="${INST_BOOKS_EXPORT_TEXT_ONLY:-0}"
MAX_VOL="${INST_BOOKS_MAX_VOLUMES:-}"

echo "[ibooks] shell=$SHELL_ROOT out=$OUT_DIR profile=$PROFILE export_text=$EXPORT_TEXT"

# shellcheck disable=SC1091
source "$SHELL_ROOT/scripts/bridges_prep_env.sh"

VENV="${INST_BOOKS_VENV:-$SHELL_ROOT/.venv-ibooks}"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PY_RUN" -m venv "$VENV"
fi
source "$VENV/bin/activate"
unset PYTHONPATH
pip install -q -U pip
pip install -q datasets pyyaml huggingface_hub

ARGS=(
  --out-dir "$OUT_DIR"
  --profile "$PROFILE"
)
[[ -n "$MAX_VOL" ]] && ARGS+=(--max-volumes "$MAX_VOL")
if [[ "$EXPORT_TEXT" == "1" ]]; then
  if [[ -z "${HF_TOKEN:-}" && -z "${HUGGING_FACE_HUB_TOKEN:-}" ]]; then
    echo "ERROR: INST_BOOKS_EXPORT_TEXT=1 requires HF_TOKEN on Bridges" >&2
    echo "  1. Accept license: https://huggingface.co/datasets/institutional/institutional-books-1.0" >&2
    echo "  2. hf auth login locally, then re-submit (token is forwarded)" >&2
    exit 1
  fi
  if [[ "$EXPORT_TEXT_ONLY" == "1" ]]; then
    ARGS+=(--export-text-only --export-text)
  else
    ARGS+=(--export-text)
  fi
fi

python3 "$SHELL_ROOT/scripts/prepare_institutional_books_corpus.py" "${ARGS[@]}"

echo "[ibooks] volumes=$(wc -l < "$OUT_DIR/manifest.jsonl")"
echo "[ibooks] stats:"
cat "$OUT_DIR/stats.json"
echo "[ibooks] done: $OUT_DIR"
