#!/usr/bin/env bash
# Wait for corpus-dl to finish, extract PageXML line images, build r3 manifest,
# wait for r2-train to finish, then launch r3-train.
#
# Run on the server in a screen:
#   screen -dmS prep-r3 bash -c 'bash ~/prep_and_launch_r3.sh 2>&1 | tee ~/prep-r3.log'

set -euo pipefail

VENV="$HOME/.venv-kraken"
CORPORA="$HOME/src/htr-corpora"
EXTRACTED="$HOME/src/htr-xml-extracted"
SRC="$HOME/src"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── 1. Wait for corpus-dl to finish ─────────────────────────────────────────

log "Waiting for corpus-dl screen to finish…"
while screen -ls 2>/dev/null | grep -q corpus-dl; do
    sleep 120
done
log "corpus-dl done."

# ── 2. Unzip Zenodo archives ──────────────────────────────────────────────────

log "Unzipping Zenodo archives…"
for corpus_dir in "$CORPORA"/*/; do
    name=$(basename "$corpus_dir")
    done_flag="$corpus_dir/.unzipped"
    [[ -f "$done_flag" ]] && continue
    found=0
    for zip in "$corpus_dir"/*.zip "$corpus_dir"/*.tar "$corpus_dir"/*.tgz "$corpus_dir"/*.tar.gz; do
        [[ -f "$zip" ]] || continue
        log "  unzipping $name/$(basename "$zip")"
        case "$zip" in
            *.zip)  unzip -q -o "$zip" -d "$corpus_dir" 2>/dev/null || true ;;
            *.tgz|*.tar.gz) tar xzf "$zip" -C "$corpus_dir" 2>/dev/null || true ;;
            *.tar)  tar xf  "$zip" -C "$corpus_dir" 2>/dev/null || true ;;
        esac
        found=1
    done
    [[ "$found" -eq 1 ]] && touch "$done_flag"
done
log "Unzip done."

# ── 3. Extract line images from PageXML/ALTO corpora ─────────────────────────

source "$VENV/bin/activate"

log "Extracting line images from PageXML corpora → $EXTRACTED"
mkdir -p "$EXTRACTED"

python3 - <<'PYEOF'
import sys, os, re
from pathlib import Path
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import numpy as np

CORPORA = Path(os.environ['HOME']) / 'src/htr-corpora'
OUT = Path(os.environ['HOME']) / 'src/htr-xml-extracted'
OUT.mkdir(parents=True, exist_ok=True)

# PageXML namespaces to try
PAGE_NS_PATTERNS = [
    r'http://schema\.primaresearch\.org/PAGE/gts/pagecontent/\S+',
]
ALTO_NS = 'http://www.loc.gov/standards/alto/ns-v4#'

def get_ns(root):
    m = re.match(r'\{([^}]+)\}', root.tag)
    return m.group(1) if m else ''

def parse_coords(pts_str):
    pts = []
    for tok in pts_str.strip().split():
        if ',' in tok:
            x, y = tok.split(',', 1)
            pts.append((int(float(x)), int(float(y))))
    return pts

def crop_line(img, coords):
    if not coords:
        return None
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    x0, x1 = max(0, min(xs)), min(img.width - 1, max(xs))
    y0, y1 = max(0, min(ys)), min(img.height - 1, max(ys))
    if x1 <= x0 or y1 <= y0:
        return None
    return img.crop((x0, y0, x1, y1))

def parse_page_xml(xml_path, img_path, out_dir, prefix):
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    ns_uri = get_ns(root)
    ns = {'ns': ns_uri} if ns_uri else {}

    img = Image.open(str(img_path)).convert('L')
    saved = 0
    line_idx = 0

    for tl in root.findall('.//ns:TextLine', ns) if ns else root.findall('.//TextLine'):
        line_idx += 1
        # Get transcription
        equiv = tl.find('ns:TextEquiv/ns:Unicode', ns) if ns else tl.find('TextEquiv/Unicode')
        if equiv is None or not (equiv.text or '').strip():
            continue
        text = equiv.text.strip()

        # Get coords (prefer Baseline, fall back to Coords)
        coords_el = tl.find('ns:Coords', ns) if ns else tl.find('Coords')
        if coords_el is None:
            continue
        pts = parse_coords(coords_el.get('points', ''))
        crop = crop_line(img, pts)
        if crop is None or crop.width < 10 or crop.height < 3:
            continue

        stem = f"{prefix}_{line_idx:05d}"
        crop.save(str(out_dir / f"{stem}.png"))
        (out_dir / f"{stem}.gt.txt").write_text(text, encoding='utf-8')
        saved += 1
    return saved

def parse_alto(xml_path, img_path, out_dir, prefix):
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    ns_uri = get_ns(root)
    ns = {'ns': ns_uri} if ns_uri else {}

    img = Image.open(str(img_path)).convert('L')
    saved = 0
    line_idx = 0

    for tl in root.findall('.//ns:TextLine', ns) if ns else root.findall('.//TextLine'):
        line_idx += 1
        # ALTO stores text in String elements
        texts = []
        for sp in tl.findall('.//ns:String', ns) if ns else tl.findall('.//String'):
            c = sp.get('CONTENT', '').strip()
            if c:
                texts.append(c)
        text = ' '.join(texts).strip()
        if not text:
            continue

        hpos = tl.get('HPOS')
        vpos = tl.get('VPOS')
        width = tl.get('WIDTH')
        height = tl.get('HEIGHT')
        if not all([hpos, vpos, width, height]):
            continue
        x0, y0 = int(float(hpos)), int(float(vpos))
        x1, y1 = x0 + int(float(width)), y0 + int(float(height))
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(img.width - 1, x1); y1 = min(img.height - 1, y1)
        if x1 <= x0 or y1 <= y0:
            continue

        crop = img.crop((x0, y0, x1, y1))
        if crop.width < 10 or crop.height < 3:
            continue

        stem = f"{prefix}_{line_idx:05d}"
        crop.save(str(out_dir / f"{stem}.png"))
        (out_dir / f"{stem}.gt.txt").write_text(text, encoding='utf-8')
        saved += 1
    return saved

# Corpora to extract: list of (name, xml_glob_pattern, image_lookup_fn)
def find_image(xml_path):
    """Try to find the image file paired with an XML."""
    stem = xml_path.stem
    for ext in ('.jpg', '.jpeg', '.png', '.tif', '.tiff'):
        candidate = xml_path.parent / (stem + ext)
        if candidate.exists():
            return candidate
    return None

total = 0
corpora_dirs = sorted(CORPORA.iterdir())
for corpus_dir in corpora_dirs:
    if not corpus_dir.is_dir():
        continue
    name = corpus_dir.name
    out_dir = OUT / name
    done_flag = out_dir / '.done'
    if done_flag.exists():
        n = len(list(out_dir.glob('*.gt.txt')))
        print(f"  {name}: already done ({n} lines)", flush=True)
        total += n
        continue

    xmls = list(corpus_dir.rglob('*.xml'))
    xmls = [x for x in xmls if 'chocomufin' not in x.name and '.git' not in str(x)]
    if not xmls:
        continue

    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for xml_path in xmls:
        img_path = find_image(xml_path)
        if img_path is None:
            continue
        prefix = f"{name}_{xml_path.stem}"[:60]
        try:
            # Detect format
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            tag = root.tag.lower()
            if 'alto' in tag:
                n += parse_alto(xml_path, img_path, out_dir, prefix)
            elif 'pcgts' in tag or 'page' in tag:
                n += parse_page_xml(xml_path, img_path, out_dir, prefix)
        except Exception as e:
            pass  # skip malformed files

    if n > 0:
        done_flag.touch()
        print(f"  {name}: {n} lines extracted", flush=True)
        total += n

print(f"\nTotal extracted: {total} line images")
PYEOF

log "Extraction complete."

# ── 4. Build r3 manifest ──────────────────────────────────────────────────────

log "Building r3 training manifest…"

python3 - <<'PYEOF'
import os, random, pathlib

random.seed(42)
SRC = pathlib.Path(os.environ['HOME']) / 'src'
CORPORA = SRC / 'htr-corpora'
EXTRACTED = SRC / 'htr-xml-extracted'

train_lines = []
eval_lines = []

# GM: all
gm_pngs = sorted((SRC/'gm-hf-gt'/'train').glob('*.png'))
train_lines += [str(f) for f in gm_pngs]
eval_lines  += [str(f) for f in sorted((SRC/'gm-hf-gt'/'test').glob('*.png'))]

# All extracted PageXML corpora: 90/10 split, no caps
if EXTRACTED.exists():
    for corpus_dir in sorted(EXTRACTED.iterdir()):
        pngs = sorted(corpus_dir.glob('*.png'))
        if not pngs:
            continue
        n_eval = max(1, len(pngs) // 10)
        random.shuffle(pngs)
        eval_lines  += [str(f) for f in pngs[:n_eval]]
        train_lines += [str(f) for f in pngs[n_eval:]]

random.shuffle(train_lines)
(SRC/'htr-r3-train.txt').write_text('\n'.join(train_lines)+'\n')
(SRC/'htr-r3-eval.txt').write_text('\n'.join(eval_lines)+'\n')
print(f"r3 train: {len(train_lines)}, eval: {len(eval_lines)}")
PYEOF

log "Manifest ready."

# ── 5. Wait for r2-train to finish ───────────────────────────────────────────

log "Waiting for r2-train to finish…"
while screen -ls 2>/dev/null | grep -q r2-train; do
    sleep 300
done
log "r2-train done."

# ── 6. Launch r3-train ────────────────────────────────────────────────────────

# Use best model from r2 if it exists, otherwise gm-hf-htr_best
BASE="$SRC/gm-htr-r2_best.mlmodel"
[ -f "$BASE" ] || BASE="$SRC/gm-hf-htr_best.mlmodel"
log "r3 base model: $BASE"

screen -dmS r3-train bash -c "
  source $VENV/bin/activate
  PYTORCH_ALLOC_CONF=expandable_segments:True \
  CUDA_MPS_PIPE_DIRECTORY=/dev/null \
  ketos \
    -d cuda:0 \
    --workers 8 \
    --precision bf16-mixed \
    train \
      -i $BASE \
      --resize union \
      -f path \
      -q early \
      --lag 20 \
      --min-epochs 5 \
      -N 100 \
      -B 64 \
      -r 0.00005 \
      --schedule reduceonplateau \
      --sched-patience 5 \
      -t $SRC/htr-r3-train.txt \
      -e $SRC/htr-r3-eval.txt \
      -o $SRC/gm-htr-r3.mlmodel \
      2>&1 | tee ~/htr-r3-\$(date +%Y%m%d-%H%M).log
  echo DONE >> ~/htr-r3-done.flag
"

log "r3-train launched. Done."
