#!/usr/bin/env bash
# Download open-license Greek HTR ground truth (ancient + medieval/Byzantine).
#
# Usage:
#   ./scripts/download_greek_htr_corpora.sh
#   OUT=~/src/htr-corpora-greek SKIP_LARGE=1 ./scripts/download_greek_htr_corpora.sh
#   SKIP_NC=1   # skip CC-BY-NC / NC-SA packs (HPGTR, LJS380)
#   SKIP_HF=1   # skip Hugging Face
#   SKIP_BESSARION=1  # skip large inscription dataset (~1+ GB)
#
# After download, regularize:
#   python scripts/regularize_latin_htr_corpus.py \
#     --registry scripts/greek_htr_corpus_registry.yaml \
#     --corpora-root "$OUT" \
#     --out-dir "${OUT%/}/../greek-corpus-gt"
#
# See docs/greek-htr-training-data.md and scripts/htr_corpora.bib.

set -euo pipefail

OUT="${OUT:-$HOME/src/htr-corpora-greek}"
SKIP_LARGE="${SKIP_LARGE:-0}"
SKIP_HF="${SKIP_HF:-0}"
SKIP_NC="${SKIP_NC:-0}"
SKIP_BESSARION="${SKIP_BESSARION:-0}"

mkdir -p "$OUT"
LOG="$OUT/download.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Greek HTR Corpora Download: $(date) ==="
echo "Output: $OUT"
echo ""

clone_or_pull() {
  local name="$1" url="$2"
  local dest="$OUT/$name"
  if [[ -d "$dest/.git" ]]; then
    echo "  [UPDATE] $name"
    git -C "$dest" pull --ff-only -q 2>/dev/null || true
  else
    echo "  [CLONE]  $name → $url"
    git clone --depth=1 -q "$url" "$dest" 2>/dev/null || echo "  [WARN]   clone failed: $url"
  fi
}

zenodo_download() {
  local name="$1" record_id="$2"
  local dest="$OUT/$name"
  mkdir -p "$dest"
  if [[ -f "$dest/.done" ]]; then
    echo "  [SKIP]   $name (already done)"
    return
  fi
  echo "  [ZENODO] $name (record $record_id)"
  local api_url="https://zenodo.org/api/records/$record_id"
  local files
  files=$(curl -sL "$api_url" | python3 -c "
import json,sys
data=json.load(sys.stdin)
for f in data.get('files', []):
    print(f['links']['self'], f['key'])
" 2>/dev/null) || { echo "  [WARN]   could not list files for $record_id"; return; }
  while IFS=' ' read -r furl fname; do
    [[ -z "${furl:-}" ]] && continue
    [[ -f "$dest/$fname" ]] && continue
    echo "    → $fname"
    curl -sL --output "$dest/$fname" "$furl" || echo "    [WARN] failed: $fname"
  done <<< "$files"
  # Expand archives in-place (typical Zenodo pack is a single zip)
  shopt -s nullglob
  for z in "$dest"/*.zip "$dest"/*.ZIP; do
    echo "    [UNZIP] $(basename "$z")"
    unzip -qo "$z" -d "$dest" || echo "    [WARN] unzip failed: $z"
  done
  shopt -u nullglob
  touch "$dest/.done"
}

hf_download() {
  local name="$1" dataset_id="$2" splits="${3:-train}"
  local dest="$OUT/$name"
  if [[ "$SKIP_HF" == "1" ]]; then
    echo "  [SKIP]   $name (SKIP_HF=1)"
    return
  fi
  mkdir -p "$dest"
  if [[ -f "$dest/.done" ]]; then
    echo "  [SKIP]   $name (already done)"
    return
  fi
  echo "  [HF]     $name ($dataset_id, splits: $splits)"
  python3 - <<PYEOF
import sys
from pathlib import Path
try:
    from datasets import load_dataset
except ImportError:
    print("datasets not installed; skipping $name")
    sys.exit(0)

def save_pairs(ds, split_dir, split):
    split_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for i, ex in enumerate(ds):
        img = ex.get("image") or ex.get("im")
        text = (ex.get("text") or ex.get("transcription") or ex.get("label") or "")
        if img is None or not str(text).strip():
            continue
        stem = f"{split}_{i:06d}"
        img_path = split_dir / f"{stem}.png"
        gt_path = split_dir / f"{stem}.gt.txt"
        img.save(str(img_path))
        gt_path.write_text(str(text).strip(), encoding="utf-8")
        saved += 1
        if saved % 500 == 0:
            print(f"  {split}: {saved}...", flush=True)
    return saved

out = Path("$dest")
total = 0
for split in "$splits".split(","):
    split = split.strip()
    try:
        ds = load_dataset("$dataset_id", split=split)
        n = save_pairs(ds, out / split, split)
        print(f"  {split}: {n} pairs saved")
        total += n
    except Exception as e:
        # some datasets only expose 'train'
        try:
            ds = load_dataset("$dataset_id", split="train")
            n = save_pairs(ds, out / "train", "train")
            print(f"  train (fallback): {n} pairs saved")
            total += n
            break
        except Exception as e2:
            print(f"  {split}: FAILED ({e}); fallback FAILED ({e2})")
print(f"  total: {total}")
Path("$dest/.done").touch()
PYEOF
}

# ── 1. Ancient Greek papyri (priority) ────────────────────────────────────

echo "--- Ancient Greek (papyri / Hellenistic) ---"
zenodo_download "zenon-papyri" "6565706"
zenodo_download "ancient-greek-transcriboquest-2025" "17062972"

if [[ "$SKIP_NC" != "1" ]]; then
  hf_download "ljs380-sextus" \
    "evndttr/LJS380_excerpts-Sextus_Empiricus_Pros_Mathematikous" \
    "train"
else
  echo "  [SKIP]   ljs380-sextus (SKIP_NC=1)"
fi

# ── 2. Byzantine / medieval Greek book hands (Zenodo PAGE packs) ────────

echo ""
echo "--- Medieval / Byzantine Greek (Zenodo) ---"
zenodo_download "eparchos" "4095301"
zenodo_download "stavronikita-53" "5595669"
zenodo_download "stavronikita-79" "5578136"
zenodo_download "stavronikita-114" "5578251"
zenodo_download "vat-gr-2228-phil-gr-130" "20705757"

# ── 3. Git / GitLab PAGE / ALTO ───────────────────────────────────────────

echo ""
echo "--- Git / GitLab Greek GT ---"
clone_or_pull "palatine-anthology-cpgr23" \
  "https://gitlab.huma-num.fr/ecrinum/anthologia/htr_cpgr23.git"
clone_or_pull "eutyches" "https://github.com/malamatenia/Eutyches.git"
# PTA helpers + model citation only (no full GT dump)
clone_or_pull "greekhtr-pta-model" "https://github.com/PatristicTextArchive/GreekHTR.git"

if [[ "$SKIP_NC" != "1" ]]; then
  clone_or_pull "hpgtr" "https://github.com/vivianpl/hpgtr.git"
  # Expand ALTO if present
  if [[ -f "$OUT/hpgtr/alto.zip" && ! -d "$OUT/hpgtr/alto" ]]; then
    echo "  [UNZIP]  hpgtr/alto.zip"
    mkdir -p "$OUT/hpgtr/alto"
    unzip -qo "$OUT/hpgtr/alto.zip" -d "$OUT/hpgtr/alto" || true
  fi
else
  echo "  [SKIP]   hpgtr (SKIP_NC=1)"
fi

if [[ "$SKIP_BESSARION" != "1" && "$SKIP_LARGE" != "1" ]]; then
  clone_or_pull "bessarion" "https://github.com/Archaeocomputers/Bessarion.git"
else
  echo "  [SKIP]   bessarion (SKIP_BESSARION or SKIP_LARGE)"
fi

# ── 4. Optional: convert HF line pairs → PageXML ─────────────────────────

if [[ "$SKIP_HF" != "1" && "$SKIP_NC" != "1" ]]; then
  echo ""
  echo "--- Converting HF Greek line pairs to PageXML ---"
  CONV_SCRIPT="$(dirname "$0")/hf_pairs_to_pagexml.py"
  if [[ -f "$CONV_SCRIPT" && -d "$OUT/ljs380-sextus" ]]; then
    python3 "$CONV_SCRIPT" "$OUT/ljs380-sextus" \
      || echo "  [WARN] conversion failed for ljs380-sextus"
  fi
fi

# ── 5. Summary ────────────────────────────────────────────────────────────

echo ""
echo "=== Download complete. Summary ==="
printf "%-45s  %8s  %8s\n" "Dataset" "XML" "images"
printf "%-45s  %8s  %8s\n" "-------" "---" "------"
total_xml=0
for dir in "$OUT"/*/; do
  [[ -d "$dir" ]] || continue
  nxml=$(find "$dir" \( -name "*.xml" -o -name "*.alto" \) 2>/dev/null | wc -l | tr -d ' ')
  nimg=$(find "$dir" \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" -o -name "*.tif" -o -name "*.tiff" \) 2>/dev/null | wc -l | tr -d ' ')
  total_xml=$((total_xml + nxml))
  printf "%-45s  %8d  %8d\n" "$(basename "$dir")" "$nxml" "$nimg"
done
echo ""
echo "Total XML/ALTO files: $total_xml"
echo "Registry: scripts/greek_htr_corpus_registry.yaml"
echo "Docs:     docs/greek-htr-training-data.md"
echo "Log:      $LOG"
