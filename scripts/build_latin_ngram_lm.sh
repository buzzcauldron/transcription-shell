#!/usr/bin/env bash
# Build a KenLM n-gram language model from the Latin GT corpus.
#
# Outputs:
#   $OUT/latin_5gram.arpa   — ARPA format (large, readable)
#   $OUT/latin_5gram.bin    — binary (fast, used at inference)
#
# Usage (on Bridges or akdeniz with kenlm installed):
#   bash scripts/build_latin_ngram_lm.sh
#   bash scripts/build_latin_ngram_lm.sh --order 3 --out /path/to/models
#
# On Bridges: pip install kenlm (or load from module)
set -euo pipefail

ORDER=5
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
OUT="${HISTORICAL_OCR_LM_DIR:-$SRC/models/lm}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --order) ORDER="$2"; shift 2 ;;
    --out)   OUT="$2";   shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$OUT"

# Collect all GT plain-text lines from the train manifest.
# Each line of the manifest is a path to a PAGE XML file; extract Unicode text.
CORPUS="$OUT/latin_corpus.txt"
echo "[build_lm] extracting text from manifest…"
python3 - <<'PYEOF'
import os, pathlib, xml.etree.ElementTree as ET

NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"
gt = pathlib.Path(os.environ.get("GT", "."))
manifest = gt / "core_train_manifest.txt"
if not manifest.is_file():
    manifest = gt / "full_train_manifest.txt"
out = pathlib.Path(os.environ["OUT"]) / "latin_corpus.txt"
lines = []
for xml_path in manifest.read_text().splitlines():
    xml_path = xml_path.strip()
    if not xml_path:
        continue
    try:
        tree = ET.parse(xml_path)
        for el in tree.findall(f".//{{{NS}}}Unicode"):
            text = (el.text or "").strip()
            if text:
                lines.append(text)
    except Exception:
        pass
out.write_text("\n".join(lines) + "\n")
print(f"[build_lm] {len(lines)} lines → {out}")
PYEOF

# Check kenlm is available.
if ! command -v lmplz &>/dev/null; then
  echo "[build_lm] lmplz not found — install kenlm: pip install kenlm" >&2
  echo "[build_lm] or on Bridges: module load kenlm (if available)" >&2
  exit 1
fi

ARPA="$OUT/latin_${ORDER}gram.arpa"
BIN="$OUT/latin_${ORDER}gram.bin"

echo "[build_lm] building ${ORDER}-gram ARPA…"
lmplz -o "$ORDER" \
  --text "$CORPUS" \
  --arpa "$ARPA" \
  --discount_fallback

echo "[build_lm] converting to binary…"
build_binary "$ARPA" "$BIN"

echo "[build_lm] done"
echo "  ARPA: $ARPA"
echo "  BIN:  $BIN (set TRANSCRIBER_SHELL_CTC_LM_PATH=$BIN)"
