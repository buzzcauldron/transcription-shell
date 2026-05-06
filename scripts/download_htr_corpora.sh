#!/usr/bin/env bash
# Download all open-license HTR training corpora for medieval Latin HTR.
# Run on the CMU training server (needs git, curl, python3, unzip).
#
# Usage:
#   CMU_HOST=seth@akdeniz.lan.cmu.edu  ./download_htr_corpora.sh   # run locally (rsync to CMU)
#   ./download_htr_corpora.sh                                        # run directly on CMU
#
# Environment:
#   OUT=~/src/htr-corpora   Output directory
#   SKIP_LARGE=1            Skip GT4HistOCR (4 GB)
#   SKIP_HF=1               Skip HuggingFace dataset downloads
#
# ── Estimated training lines ───────────────────────────────────────────────
# HuggingFace parquet datasets (converted to PageXML):
#   CATMuS/medieval               ~153,000 lines  Latin+French+Spanish+Italian
#   magistermilitum/Tridis        ~177,000 lines  Latin+French charters
#   mzzhang2014/glyph_machina       3,603 lines  (already done)
#
# GitHub PAGE/ALTO XML repos:
#   HTRomance medieval-latin        9,008 lines  Latin manuscripts
#   HTRomance middle-ages-in-spain  4,504 lines  Latin+Spanish
#   HTRomance medieval-italian      ~7,000 lines  Italian+Latin
#   HTRomance medieval-french      10,769 lines  Old French
#   CREMMA Medii Aevi               7,274 lines  Latin manuscripts 11-16c
#   CREMMA Medieval (fr+lat)       22,848 lines  Old French+Latin
#   Carolingian Latin Vienna        7,835 lines  Latin 800-900
#   iForal Dataset                  8,009 lines  Latin medieval charters
#   Paris Bible Project             1,700 lines  Latin Bible
#   CIHAM Liber                     3,789 lines  Latin
#   Caroline Minuscule               457 lines  Latin
#   Bullinger HTR                 165,673 lines  Latin+German letters 16-17c
#   OCR-D GT Structure Text         6,608 lines  Latin+German
#   CREMMA Early Modern Books       2,603 lines  Latin+French printed
#
# Zenodo downloads:
#   Königsfelden Charters          60,000 lines  Latin+German charters
#   ANR e-NDP                      34,231 lines  French+Latin registers
#   HTRomance Documentary         120,000 lines  Latin+French (Alcar+eNDP+HIMANIS)
#   HIMANIS-Guérin                 30,000 lines  Latin+Old French
#   Gwalther Handwriting            4,040 lines  Latin letters
#   TranscriboQuest 2024 Medieval     800 lines  Latin+multilingual
#   HOME Medieval Charters           ~500 lines  Latin+multilingual 11-16c
#   Polish Latin Transcribathon       ~11 docs  Latin (Polish Crown Chancery)
#   GT4HistOCR (printed)          313,173 lines  Early Modern Latin+German
#
# ── Grand total: ~1,200,000+ lines ────────────────────────────────────────

set -euo pipefail

OUT="${OUT:-$HOME/src/htr-corpora}"
SKIP_LARGE="${SKIP_LARGE:-0}"
SKIP_HF="${SKIP_HF:-0}"

mkdir -p "$OUT"
LOG="$OUT/download.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== HTR Corpora Download: $(date) ==="
echo "Output: $OUT"
echo ""

# ── helpers ──────────────────────────────────────────────────────────────────

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
    [[ -z "$furl" ]] && continue
    [[ -f "$dest/$fname" ]] && continue
    echo "    → $fname"
    curl -sL --output "$dest/$fname" "$furl" || echo "    [WARN] failed: $fname"
  done <<< "$files"
  touch "$dest/.done"
}

hf_download() {
  local name="$1" dataset_id="$2" splits="${3:-train,validation}"
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
  source ~/src/.venv/bin/activate 2>/dev/null || true
  python3 - <<PYEOF
import sys, os
sys.path.insert(0, os.path.expanduser('~/src'))
from pathlib import Path
from PIL import Image

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
        if saved % 1000 == 0:
            print(f"  {split}: {saved}...", flush=True)
    return saved

try:
    from datasets import load_dataset
except ImportError:
    print("datasets not installed; skipping $name")
    sys.exit(0)

out = Path("$dest")
total = 0
for split in "$splits".split(","):
    split = split.strip()
    split_dir = out / split
    try:
        ds = load_dataset("$dataset_id", split=split)
        n = save_pairs(ds, split_dir, split)
        print(f"  {split}: {n} pairs saved")
        total += n
    except Exception as e:
        print(f"  {split}: FAILED ({e})")
print(f"  total: {total}")
Path("$dest/.done").touch()
PYEOF
}

# ── 1. HuggingFace datasets (line images + text → PNG + .gt.txt) ───────────

echo "--- HuggingFace datasets ---"

hf_download "catmus-medieval"    "CATMuS/medieval"          "train,validation,test"
hf_download "tridis"             "magistermilitum/Tridis"   "train,validation,test"

# ── 2. Medieval Latin manuscripts (GitHub PAGE/ALTO XML) ──────────────────

echo ""
echo "--- Medieval Latin manuscripts (GitHub) ---"

clone_or_pull "cremma-medieval-lat"       "https://github.com/HTR-United/CREMMA-Medieval-LAT.git"
clone_or_pull "htromance-medieval-latin"  "https://github.com/HTRomance-Project/medieval-latin.git"
clone_or_pull "htromance-medieval-italian" "https://github.com/HTRomance-Project/medieval-italian.git"
clone_or_pull "carolingian-latin-vienna"  "https://github.com/HTR-School-Vienna/-2024--carolingian-latin.git"
clone_or_pull "carolingian-latin-2025"    "https://github.com/HTR-School-Vienna/2025--Carolingian_Latin-.git"
clone_or_pull "iforal"                    "https://github.com/Arch-W/iForal-Dataset.git"
clone_or_pull "ciham-liber"               "https://github.com/CIHAM-HTR/Liber.git"
clone_or_pull "paris-bible"               "https://github.com/parisbible/ground_truth.git"
clone_or_pull "caroline-minuscule"        "https://github.com/rescribe/carolineminuscule-groundtruth.git"
clone_or_pull "htromance-spain"           "https://github.com/HTRomance-Project/middle-ages-in-spain.git"
clone_or_pull "htromance-medieval-french" "https://github.com/HTRomance-Project/medieval-french.git"
clone_or_pull "boccace-htr"               "https://github.com/PSL-Chartes-HTR-Students/HN2021-Boccace.git"
clone_or_pull "eutyches"                  "https://github.com/malamatenia/Eutyches.git"

# ── 3. Multi-language (Latin + French/German/Italian) ─────────────────────

echo ""
echo "--- Multi-language with Latin (GitHub) ---"

clone_or_pull "cremma-medieval"           "https://github.com/HTR-United/cremma-medieval.git"
clone_or_pull "cremma-early-modern"       "https://github.com/HTR-United/cremma-16-17-print.git"
clone_or_pull "bullinger-htr"             "https://github.com/pstroe/bullinger-htr.git"
clone_or_pull "ocrd-gt-structure-text"    "https://github.com/OCR-D/gt_structure_text.git"

# ── 4. Zenodo datasets ────────────────────────────────────────────────────

echo ""
echo "--- Zenodo datasets ---"

# Königsfelden Charters (60,000 lines, Latin+German)
zenodo_download "konigsfelden-charters"   "5179361"

# ANR e-NDP (34,231 lines, French+Latin Notre-Dame registers)
zenodo_download "anr-endp"                "7575693"

# HTRomance Latin+French Documentary (120,000 lines: ALCAR+eNDP+HIMANIS)
zenodo_download "htromance-documentary"   "7401833"

# HIMANIS-Guérin (30,000 lines, Latin+Old French royal charters)
zenodo_download "himanis"                 "5600884"

# Gwalther Handwriting (4,040 lines, Latin 16th-c letters)
zenodo_download "gwalther"                "4780947"

# HTRomance Medieval Italian (Zenodo version)
zenodo_download "htromance-italian"       "14718897"

# TranscriboQuest 2024 Medieval (800 lines, multilingual)
zenodo_download "transcriboqurest-2024"   "13757440"

# ÖNB Carolingian Cod 940 (7,835 lines, Latin)
zenodo_download "onb-cod-940"             "7467249"

# HOME Medieval Charters (multilingual, Latin 11-16c, named entities)
zenodo_download "home-charters"           "1194357"

# 1st Medieval Latin Transcribathon – Polish Crown Chancery Records
zenodo_download "polish-latin-transcribathon" "7360546"

# ── 5. GT4HistOCR printed corpus (4 GB, optional) ────────────────────────

echo ""
echo "--- GT4HistOCR printed corpus ---"

if [[ "$SKIP_LARGE" != "1" ]]; then
  GT4DIR="$OUT/gt4histocr"
  mkdir -p "$GT4DIR"
  if [[ ! -f "$GT4DIR/.done" ]]; then
    echo "  [DOWNLOAD] GT4HistOCR (4 GB, CC-BY 4.0)..."
    curl -L --progress-bar \
      "https://zenodo.org/api/records/1344132/files/GT4HistOCR.tar?download=1" \
      -o "$GT4DIR/GT4HistOCR.tar"
    echo "  [EXTRACT]..."
    tar xf "$GT4DIR/GT4HistOCR.tar" -C "$GT4DIR" --strip-components=1
    rm "$GT4DIR/GT4HistOCR.tar"
    touch "$GT4DIR/.done"
  else
    echo "  [SKIP]   GT4HistOCR (already done)"
  fi
else
  echo "  [SKIP]   GT4HistOCR (SKIP_LARGE=1)"
fi

# ── 6. Convert HF PNG+.gt.txt pairs to PageXML ───────────────────────────

if [[ "$SKIP_HF" != "1" ]]; then
  echo ""
  echo "--- Converting HF pairs to PageXML ---"
  CONV_SCRIPT="$(dirname "$0")/hf_pairs_to_pagexml.py"
  if [[ -f "$CONV_SCRIPT" ]]; then
    for hf_dir in "$OUT/catmus-medieval" "$OUT/tridis"; do
      [[ -d "$hf_dir" ]] || continue
      name=$(basename "$hf_dir")
      echo "  converting $name..."
      python3 "$CONV_SCRIPT" "$hf_dir" || echo "  [WARN] conversion failed for $name"
    done
  else
    echo "  [INFO] run scripts/hf_pairs_to_pagexml.py separately on HF dirs"
  fi
fi

# ── 7. Count results ──────────────────────────────────────────────────────

echo ""
echo "=== Download complete. Summary ==="
printf "%-45s  %8s\n" "Dataset" "XML files"
printf "%-45s  %8s\n" "-------" "---------"
total=0
for dir in "$OUT"/*/; do
  [[ ! -d "$dir" ]] && continue
  n=$(find "$dir" -name "*.xml" | wc -l)
  total=$((total + n))
  printf "%-45s  %8d\n" "$(basename "$dir")" "$n"
done
echo ""
echo "Total XML files: $total"
echo ""
echo "PNG+.gt.txt pairs (HuggingFace, unconverted):"
for hf_dir in catmus-medieval tridis; do
  n=$(find "$OUT/$hf_dir" -name "*.gt.txt" 2>/dev/null | wc -l)
  printf "  %-40s  %8d pairs\n" "$hf_dir" "$n"
done
