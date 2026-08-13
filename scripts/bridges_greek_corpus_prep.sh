#!/usr/bin/env bash
# Regularize Greek HTR corpora on Bridges2 and write minuscule/papyrus manifests.
# Called from r_greek_minuscule_retrain.sbatch (compute node — not login).
#
# Environment:
#   SRC           default: /ocean/.../transcriber-shell/src
#   GREEK_CORPORA default: $SRC/htr-corpora-greek
#   GT            default: $SRC/greek-corpus-gt

set -euo pipefail

SRC="${SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
GREEK_CORPORA="${GREEK_CORPORA:-$SRC/htr-corpora-greek}"
GT="${GT:-$SRC/greek-corpus-gt}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# shellcheck disable=SC1091
source "$HERE/bridges_prep_env.sh"

cd "$SRC"
echo "[greek-prep] python: $($PY_RUN --version 2>&1)"
echo "[greek-prep] corpora: $GREEK_CORPORA"
echo "[greek-prep] out GT:  $GT"

if [[ ! -d "$GREEK_CORPORA" ]]; then
  echo "ERROR: htr-corpora-greek missing at $GREEK_CORPORA" >&2
  echo "  rsync from Mac: bash scripts/rsync_greek_corpora_to_bridges.sh" >&2
  exit 1
fi

"$PY_RUN" -c "import yaml" 2>/dev/null || "$PY_RUN" -m pip install -q pyyaml

"$PY_RUN" "$HERE/regularize_latin_htr_corpus.py" \
  --registry "$HERE/greek_htr_corpus_registry.yaml" \
  --corpora-root "$GREEK_CORPORA" \
  --out-dir "$GT" \
  --src-root "$SRC" \
  --min-samples "${GREEK_MIN_SAMPLES:-50}" \
  --workers 8

"$PY_RUN" "$HERE/split_greek_manifests.py" --gt-dir "$GT"

echo "[greek-prep] manifests:"
for f in greek_minuscule_train greek_minuscule_val greek_papyrus_train greek_papyrus_val greek_all_train greek_all_val; do
  p="$GT/${f}_manifest.txt"
  if [[ -f "$p" ]]; then
    echo "  $f: $(wc -l < "$p")"
  fi
done
echo "[greek-prep] done."
