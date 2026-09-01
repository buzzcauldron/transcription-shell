#!/usr/bin/env bash
# Queue computus.lat IIIF manuscripts for strigil acquire-only on a remote host.
#
# Prefer the full harvest orchestrator for the union registry workflow:
#   bash scripts/computus/run_web_harvest.sh
#
# This script builds a structured JSONL acquire queue (not a fragile TSV)
# and optionally installs a remote worker via run_acquire_queue.py.
# Robots policy is respected (no --no-robots).
#
# Usage:
#   bash scripts/batch_scrape_computus_lat.sh [--dry-run] [--limit N] [--remote HOST]
#   bash scripts/batch_scrape_computus_lat.sh --install-queue [--concurrency 2]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE="${STREAM_REMOTE:-akdeniz}"
CATALOG_URL='https://raw.githubusercontent.com/thomsnijders/thomsnijders.github.io/main/json/ms-catalog.json'
LOCAL_CATALOG="$ROOT/references/computus-library/computus_lat_ms-catalog.json"
QUEUE_FILE="$ROOT/references/computus-library/web_harvest/queues/computus_lat_scrape_queue.jsonl"
DRY_RUN=false
LIMIT=0
CONCURRENCY=2
INSTALL_QUEUE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --install-queue) INSTALL_QUEUE=true; shift ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$ROOT/references/computus-library/web_harvest/queues"
if [[ ! -f "$LOCAL_CATALOG" ]]; then
  echo "Fetching computus.lat MS catalogue..."
  curl -fsSL "$CATALOG_URL" -o "$LOCAL_CATALOG"
fi

existing=$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$REMOTE" 'ls /mnt/constantinople/seth/latin-ms-workspace/jobs/ 2>/dev/null || ls "$HOME/latin-ms-workspace/jobs/" 2>/dev/null || true')
export EXISTING_JOBS="$existing"
export LOCAL_CATALOG QUEUE_FILE LIMIT

python3 - <<'PY'
import json, os, re, urllib.parse
from pathlib import Path

ms = json.loads(Path(os.environ["LOCAL_CATALOG"]).read_text(encoding="utf-8"))
existing = set(os.environ.get("EXISTING_JOBS", "").split())
limit = int(os.environ.get("LIMIT") or "0")

def urls_from(rec):
    out = []
    for field in ("IIIF", "Digitalizations"):
        v = rec.get(field)
        if not v:
            continue
        for part in re.split(r"[\s,]+", str(v)):
            part = part.strip().rstrip(",")
            if not part:
                continue
            if part.startswith("//"):
                part = "https:" + part
            if part.startswith("http"):
                out.append(part)
    manifests = [u for u in out if "manifest" in u.lower()]
    return manifests or out

def job_id(shelf: str, msid) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (shelf or "").lower())
    s = re.sub(r"_+", "_", s).strip("_")[:40].rstrip("_")
    return f"clat_{msid}_{s}"[:60]

def flags_for(url: str) -> list[str]:
    flags: list[str] = []
    if any(
        x in url
        for x in (
            "bl.uk",
            "wellcomecollection",
            "morgan.org",
            "diglib.hab.de",
            "internetculturale.it",
            "digital.staatsbibliothek-berlin.de",
        )
    ):
        flags.append("--js")
    stripped = url.split("?")[0]
    if (
        "gallica.bnf.fr" in url
        or stripped.endswith("/manifest")
        or stripped.endswith("/manifest.json")
        or "manifest" in stripped.lower()
    ):
        flags.extend(["--source", "iiif"])
    return flags

seen_url = set()
rows = []
for rec in ms:
    if not (rec.get("IIIF") or "").strip():
        continue
    urls = urls_from(rec)
    if not urls:
        continue
    url = urls[0]
    if url in seen_url:
        continue
    seen_url.add(url)
    jid = job_id(rec.get("Shelfmark") or "", rec.get("MSID"))
    if jid in existing:
        continue
    rows.append(
        {
            "job_id": jid,
            "record_id": f"clat_{rec.get('MSID')}",
            "url": url,
            "flags": flags_for(url),
            "shelfmark": rec.get("Shelfmark") or "",
            "host": urllib.parse.urlparse(url).netloc.lower(),
            "reason": "catalogue_iiif",
        }
    )

if limit > 0:
    rows = rows[:limit]

out = Path(os.environ["QUEUE_FILE"])
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
print(f"Wrote {len(rows)} queue rows → {out}")
PY

N=$(wc -l < "$QUEUE_FILE" | tr -d ' ')
echo "Queue size: $N"
echo "First 8:"
head -8 "$QUEUE_FILE"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "(dry run — not installing remote worker)"
  exit 0
fi

if [[ "$INSTALL_QUEUE" != "true" ]]; then
  echo "Re-run with --install-queue to start acquire-only worker on $REMOTE (concurrency=$CONCURRENCY)."
  echo "Or use: bash scripts/computus/run_web_harvest.sh"
  exit 0
fi

ssh -o BatchMode=yes "$REMOTE" 'mkdir -p /mnt/constantinople/seth/latin-ms-workspace/computus_web_harvest/{queues,logs} || mkdir -p "$HOME/latin-ms-workspace/computus_web_harvest/{queues,logs}"'

REMOTE_TS="$(cd "$ROOT" && git rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
# Sync scripts into the checkout on the remote host
rsync -az \
  "$ROOT/scripts/computus/run_acquire_queue.py" \
  "$ROOT/scripts/batch_scrape_computus_lat.sh" \
  "$REMOTE:/tmp/computus_acquire_sync/"
rsync -az "$QUEUE_FILE" "$REMOTE:/mnt/constantinople/seth/latin-ms-workspace/computus_web_harvest/queues/computus_lat_scrape_queue.jsonl" 2>/dev/null \
  || rsync -az "$QUEUE_FILE" "$REMOTE:latin-ms-workspace/computus_web_harvest/queues/computus_lat_scrape_queue.jsonl"

ssh -o BatchMode=yes "$REMOTE" "bash -s" <<EOF
set -euo pipefail
Q=/mnt/constantinople/seth/latin-ms-workspace/computus_web_harvest
if [[ ! -d \$Q ]]; then Q=\$HOME/latin-ms-workspace/computus_web_harvest; fi
JOBS=/mnt/constantinople/seth/latin-ms-workspace/jobs
if [[ ! -d \$JOBS ]]; then JOBS=\$HOME/latin-ms-workspace/jobs; fi
STRIGIL=/mnt/constantinople/seth/Projects/strigil
if [[ ! -d \$STRIGIL ]]; then STRIGIL=\$HOME/Projects/strigil; fi
PY=\$HOME/.venv-strigil/bin/python
[[ -x \$PY ]] || PY=python3
mkdir -p "\$Q/logs" "\$Q/queues"
# prefer transcription-shell checkout if present
ACQ=/mnt/constantinople/seth/Projects/transcription-shell/scripts/computus/run_acquire_queue.py
if [[ ! -f \$ACQ ]]; then ACQ=/tmp/computus_acquire_sync/run_acquire_queue.py; fi
if [[ -f \$Q/queue_worker.pid ]]; then
  kill \$(cat \$Q/queue_worker.pid) 2>/dev/null || true
fi
nohup \$PY \$ACQ \\
  --queue \$Q/queues/computus_lat_scrape_queue.jsonl \\
  --jobs-root \$JOBS \\
  --strigil-dir \$STRIGIL \\
  --python \$PY \\
  --global-concurrency $CONCURRENCY \\
  >\$Q/logs/queue_worker.log 2>&1 &
echo \$! >\$Q/queue_worker.pid
sleep 2
echo "started queue worker pid=\$(cat \$Q/queue_worker.pid) concurrency=$CONCURRENCY"
head -20 \$Q/logs/queue_worker.log || true
EOF

echo "Installed acquire-only JSONL queue on $REMOTE (concurrency=$CONCURRENCY, no HTR, no --no-robots)."
