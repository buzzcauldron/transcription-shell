#!/usr/bin/env bash
# Wait for BAV Pal. lat. 1407 transcription to finish on akdeniz, then add it to
# comparative PCA and open the browser report locally.
#
# Usage:
#   bash scripts/watch_vatlat_comparative_pca.sh
#   bash scripts/watch_vatlat_comparative_pca.sh --force   # run now with current text
set -euo pipefail

REMOTE="${STREAM_REMOTE:-akdeniz}"
JOB="/home/seth/latin-ms-workspace/jobs/pal_lat_1407"
STYLO="/Users/halxiii/Projects/stylometry-r"
LOCAL_JOB="/Users/halxiii/latin-ms-workspace/jobs/pal_lat_1407"
LOCAL_TEXT="$LOCAL_JOB/pal_lat_1407_whole_manuscript_text.txt"
TARGETS_CSV="$STYLO/output/comparative_mss_pca/comparative_targets.csv"
REPORT="$STYLO/output/comparative_mss_pca/comparative_mss_pca_report.html"
POLL="${POLL:-300}"
FORCE=0
WATCH_AFTER=1
PARTIAL=0
LOG="$LOCAL_JOB/logs/watch_comparative_pca.log"

log() { echo "[vatlat-pca] $(date -Iseconds) $*" >> "$LOG"; echo "[vatlat-pca] $(date -Iseconds) $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; PARTIAL=1; shift ;;
    --once) WATCH_AFTER=0; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$LOCAL_JOB/logs" "$STYLO/output/comparative_mss_pca"

remote_status() {
  ssh -o BatchMode=yes "$REMOTE" "python3 - <<'PY'
from pathlib import Path
import os
job = Path('$JOB')
pages = len(list((job / '01_pages_2500').glob('*.jpg')))
done = len(list((job / '03_artifacts_2500').rglob('*_transcription.yaml')))
failed = len(list((job / '03_artifacts_2500').rglob('.failed')))
running = False
for pidfile in (job / 'status').glob('*.pid'):
    try:
        os.kill(int(pidfile.read_text().strip()), 0)
        running = True
    except Exception:
        pass
print(f'{pages}\t{done}\t{failed}\t{int(running)}')
PY"
}

sync_text() {
  log "syncing transcription YAMLs from $REMOTE"
  rsync -az "${REMOTE}:${JOB}/03_artifacts_2500/" "$LOCAL_JOB/03_artifacts_2500/"
  python3 - <<'PY'
import re
from pathlib import Path
import yaml

job = Path("/Users/halxiii/latin-ms-workspace/jobs/pal_lat_1407")
art = job / "03_artifacts_2500"
parts = []
pages = 0
for ypath in sorted(art.rglob("*_transcription.yaml")):
    try:
        data = yaml.safe_load(ypath.read_text(encoding="utf-8")) or {}
    except Exception:
        continue
    segs = data.get("transcriptionOutput", {}).get("segments", [])
    texts = []
    for seg in segs:
        if isinstance(seg, dict) and isinstance(seg.get("text"), str):
            text = re.sub(r"\[(?:illegible|unclear|gap|omitted)[^\]]*\]", " ", seg["text"], flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            texts.append(text.strip())
    page = " ".join(x for x in texts if x)
    if page:
        pages += 1
        parts.append(f"\n\n### {ypath.parent.name}\n{page}")
out = job / "pal_lat_1407_whole_manuscript_text.txt"
out.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
print(pages, out.stat().st_size)
PY
}

update_targets_csv() {
  python3 - <<PY
import csv
import os
from pathlib import Path

partial = os.environ.get("PARTIAL", "0") == "1"
label = "BAV Pal. lat. 1407 (partial)" if partial else "BAV Pal. lat. 1407"
source_type = "HTR manuscript (partial)" if partial else "HTR manuscript"
path = Path("/Users/halxiii/Projects/stylometry-r/output/comparative_mss_pca/comparative_targets.csv")
rows = list(csv.DictReader(path.open(encoding="utf-8")))
base = [r for r in rows if r["slug"] != "vatlat_pal1407"]
base.append({
    "slug": "vatlat_pal1407",
    "label": label,
    "source_type": source_type,
    "path": "/Users/halxiii/latin-ms-workspace/jobs/pal_lat_1407/pal_lat_1407_whole_manuscript_text.txt",
    "tokens": "0",
})
with path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["slug", "label", "source_type", "path", "tokens"])
    writer.writeheader()
    writer.writerows(base)
PY
}

run_pca_and_open() {
  export PARTIAL="$PARTIAL"
  sync_text
  pages_size=$(wc -l < "$LOCAL_TEXT" || echo 0)
  if [[ ! -s "$LOCAL_TEXT" ]]; then
    log "no text extracted yet"
    return 1
  fi
  log "extracted text ready ($pages_size lines partial=$PARTIAL)"
  update_targets_csv
  log "running comparative PCA"
  Rscript "$STYLO/scripts/run_comparative_mss_pca.R"
  python3 "$STYLO/scripts/build_comparative_mss_pca_report.py"
  log "opening $REPORT (partial=$PARTIAL)"
  open "$REPORT"
}

if [[ "$FORCE" -eq 1 ]]; then
  run_pca_and_open
  if [[ "$WATCH_AFTER" -eq 0 ]]; then
    exit 0
  fi
  PARTIAL=0
  log "partial PCA done; continuing to watch for full manuscript completion"
fi

log "watching $REMOTE:$JOB for completion"
while true; do
  status="$(remote_status 2>/dev/null || true)"
  IFS=$'\t' read -r pages done failed running <<< "${status:-0	0	0	1}"
  pages=${pages:-0}
  done=${done:-0}
  failed=${failed:-0}
  running=${running:-1}
  log "status pages=$pages done=$done failed=$failed running=$running"
  if [[ "$pages" -gt 0 && "$done" -ge "$pages" && "$running" -eq 0 ]]; then
    log "pipeline complete"
    run_pca_and_open
    exit 0
  fi
  sleep "$POLL"
done
