#!/usr/bin/env bash
# Queue computus.lat IIIF manuscripts for strigil acquire-only on a remote host.
#
# Scraping is network-bound; this deliberately does NOT start HTR watchers.
# Default: akdeniz, concurrency 2, skip jobs that already exist.
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
QUEUE_FILE="$ROOT/references/computus-library/computus_lat_scrape_queue.tsv"
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

mkdir -p "$ROOT/references/computus-library"
if [[ ! -f "$LOCAL_CATALOG" ]]; then
  echo "Fetching computus.lat MS catalogue..."
  curl -fsSL "$CATALOG_URL" -o "$LOCAL_CATALOG"
fi

existing=$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$REMOTE" 'ls "$HOME/latin-ms-workspace/jobs/" 2>/dev/null || true')
export EXISTING_JOBS="$existing"
export LOCAL_CATALOG QUEUE_FILE LIMIT

python3 - <<'PY'
import json, os, re
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
    flags = "--source iiif" if "manifest" in url.lower() else ""
    # Prefer --no-robots for Gallica (robots often block automated fetch)
    if "gallica.bnf.fr" in url and "--no-robots" not in flags:
        flags = (flags + " --no-robots").strip()
    rows.append((jid, url, flags, rec.get("Shelfmark") or ""))

if limit > 0:
    rows = rows[:limit]

out = Path(os.environ["QUEUE_FILE"])
with out.open("w", encoding="utf-8") as f:
    for jid, url, flags, shelf in rows:
        shelf = shelf.replace("\t", " ").replace("\n", " ")
        f.write(f"{jid}\t{url}\t{flags}\t{shelf}\n")
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
  exit 0
fi

WORKER_LOCAL=$(mktemp)
cat > "$WORKER_LOCAL" <<'WORKER'
#!/usr/bin/env bash
set -uo pipefail
QUEUE="${1:?queue.tsv}"
CONCURRENCY="${2:-2}"
JOBS_ROOT="${HOME}/latin-ms-workspace/jobs"
STRIGIL_DIR="${HOME}/Projects/strigil"
STRIGIL_PY="${HOME}/.venv-strigil/bin/python"
# Prefer absolute constantinople paths when present (akdeniz alt drive).
if [[ -d /mnt/constantinople/seth/latin-ms-workspace/jobs ]]; then
  JOBS_ROOT=/mnt/constantinople/seth/latin-ms-workspace/jobs
fi
if [[ -d /mnt/constantinople/seth/Projects/strigil ]]; then
  STRIGIL_DIR=/mnt/constantinople/seth/Projects/strigil
fi
[[ -x "$STRIGIL_PY" ]] || STRIGIL_PY=python3
mkdir -p "${JOBS_ROOT%/jobs}/computus_lat_queue/logs" "$JOBS_ROOT"

active_acquires() {
  pgrep -af -u "$USER" '[Pp]ython.*strigil\.cli' 2>/dev/null | wc -l | tr -d ' '
}

job_busy() {
  local job="$1" pidfile="$job/status/acquire_full.pid" pid
  [[ -f "$pidfile" ]] || return 1
  pid=$(tr -d ' \n' < "$pidfile")
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

while IFS=$'\t' read -r jid url flags shelf || [[ -n "${jid:-}" ]]; do
  [[ -z "${jid:-}" ]] && continue
  job="$JOBS_ROOT/$jid"
  nimg=0
  if [[ -d "$job/00_sources_chunks/full" ]]; then
    nimg=$(find "$job/00_sources_chunks/full" -type f 2>/dev/null | wc -l | tr -d ' ')
  fi
  if [[ "${nimg:-0}" -gt 5 ]]; then
    echo "[skip done] $jid ($nimg images)"
    continue
  fi
  if job_busy "$job"; then
    echo "[skip running] $jid"
    continue
  fi
  while true; do
    n=$(active_acquires); n=${n:-0}
    [[ "$n" -lt "$CONCURRENCY" ]] && break
    echo "[wait] active strigil=$n >= $CONCURRENCY"
    sleep 30
  done
  mkdir -p "$job/00_sources_chunks/full" "$job/logs" "$job/status"
  printf '%s\n' "$shelf" > "$job/shelfmark.txt"
  printf '%s\n' "$url" > "$job/source_url.txt"
  echo "[launch $(date -Iseconds)] $jid"
  (
    cd "$STRIGIL_DIR" || exit 0
    export PYTHONPATH="$STRIGIL_DIR"
    # shellcheck disable=SC2086
    nohup "$STRIGIL_PY" -m strigil.cli \
      --url "$url" \
      --out-dir "$job/00_sources_chunks/full" \
      --types images \
      --manuscript \
      --min-image-size 200k \
      --no-progress \
      --workers 4 \
      $flags \
      >"$job/logs/acquire_full.log" 2>&1 &
    echo $! >"$job/status/acquire_full.pid"
  )
  sleep 5
done < "$QUEUE"
echo "[queue] finished submitting all rows $(date -Iseconds)"
WORKER

ssh -o BatchMode=yes "$REMOTE" 'mkdir -p "$HOME/latin-ms-workspace/computus_lat_queue/logs"'
rsync -az "$QUEUE_FILE" "$REMOTE:latin-ms-workspace/computus_lat_queue/queue.tsv"
rsync -az "$WORKER_LOCAL" "$REMOTE:latin-ms-workspace/computus_lat_queue/run_queue.sh"
rsync -az "$LOCAL_CATALOG" "$REMOTE:latin-ms-workspace/computus_lat_queue/ms-catalog.json"
ssh -o BatchMode=yes "$REMOTE" 'chmod +x "$HOME/latin-ms-workspace/computus_lat_queue/run_queue.sh"'

ssh -o BatchMode=yes "$REMOTE" "bash -s" <<EOF
set -e
Q=\$HOME/latin-ms-workspace/computus_lat_queue
if [[ -f \$Q/queue_worker.pid ]]; then
  kill \$(cat \$Q/queue_worker.pid) 2>/dev/null || true
fi
nohup bash \$Q/run_queue.sh \$Q/queue.tsv $CONCURRENCY >\$Q/logs/queue_worker.log 2>&1 &
echo \$! >\$Q/queue_worker.pid
sleep 2
echo "started queue worker pid=\$(cat \$Q/queue_worker.pid) concurrency=$CONCURRENCY"
head -20 \$Q/logs/queue_worker.log || true
EOF

rm -f "$WORKER_LOCAL"
echo "Installed acquire-only queue on $REMOTE (concurrency=$CONCURRENCY, no HTR watchers)."
