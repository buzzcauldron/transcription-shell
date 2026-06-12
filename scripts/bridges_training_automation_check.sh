#!/usr/bin/env bash
# Bridges training health check for Cursor Automations (or manual runs).
#
# Usage:
#   bash scripts/bridges_training_automation_check.sh
#   bash scripts/bridges_training_automation_check.sh --json
#
# Exit codes:
#   0  all critical jobs healthy or progressing
#   1  attention needed (failed job, missing artifact, stuck dependency)
#   2  cannot reach Bridges (SSH)
set -euo pipefail

LOGIN="${BRIDGES_LOGIN:-bridges2}"
USER="${BRIDGES_USER:-sstrickland}"
SRC="${BRIDGES_SHELL_SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
JSON=0
[[ "${1:-}" == "--json" ]] && JSON=1

ssh_cmd() {
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$LOGIN" "$@"
}

report() {
  if [[ "$JSON" -eq 1 ]]; then
    return
  fi
  echo "$@"
}

if ! ssh_cmd "echo ok" >/dev/null 2>&1; then
  report "FAIL: cannot SSH to $LOGIN (BatchMode)"
  exit 2
fi

read -r -d '' REMOTE_SCRIPT <<'EOS' || true
set -euo pipefail
SRC="${SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
USER="${USER:-sstrickland}"

issues=0
warn() { echo "WARN|$*"; }
fail() { echo "FAIL|$*"; issues=$((issues + 1)); }
ok()   { echo "OK|$*"; }

# ── Queue ─────────────────────────────────────────────────────────────────────
echo "==QUEUE=="
squeue -u "$USER" -o "%.10i %.16j %.8T %.12M %R" 2>/dev/null | head -20 || true

# Orphaned dependencies block the chain
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  fail "orphan dependency: $line"
done < <(squeue -u "$USER" -h -o "%i %j %r" 2>/dev/null | awk '$3 == "DependencyNeverSatisfied" {print $0}')

# ── Recent failures (24h) for training job names ────────────────────────────
echo "==RECENT_FAIL=="
sacct -u "$USER" --starttime=$(date -d '24 hours ago' +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -v-1d +%Y-%m-%dT%H:%M:%S) \
  --format=JobID,JobName%18,State,ExitCode,Elapsed -n 2>/dev/null \
  | grep -E 'htr-r6|htr-r7|anglican|tess-pre|ibooks|comma|newspaper|page-cnn|tess-train' \
  | grep -E 'FAILED|TIMEOUT|CANCELLED' | tail -15 || true

for jname in htr-r6-core htr-r7-full htr-anglicana tess-pre1800 ibooks-ia; do
  state=$(sacct -u "$USER" --name="$jname" --starttime=$(date -d '48 hours ago' +%Y-%m-%d 2>/dev/null || date -v-2d +%Y-%m-%d) \
    --format=JobName,State,ExitCode -P -n 2>/dev/null | tail -1 | cut -d'|' -f2 || echo "")
  if [[ "$state" == "FAILED" || "$state" == "TIMEOUT" ]]; then
    fail "latest $jname ended $state"
  elif squeue -u "$USER" -h -o "%j %T" 2>/dev/null | awk -v n="$jname" '$1==n && $2=="RUNNING" {found=1} END{exit !found}' ; then
    ok "$jname RUNNING"
  elif squeue -u "$USER" -h -o "%j %T" 2>/dev/null | awk -v n="$jname" '$1==n && $2=="PENDING" {found=1} END{exit !found}' ; then
    ok "$jname PENDING"
  else
    warn "$jname not in queue (check sacct)"
  fi
done

# ── Artifacts ───────────────────────────────────────────────────────────────
echo "==ARTIFACTS=="
for f in \
  "$SRC/latin-corpus-gt/metadata.jsonl" \
  "$SRC/latin-corpus-gt/core_train_manifest.txt" \
  "$SRC/gm-htr-r6-core_best.mlmodel" \
  "$SRC/gm-htr-r7-full_best.mlmodel" \
  "$SRC/models/lat_pre1800.traineddata"; do
  if [[ -s "$f" ]]; then
    ok "$(basename "$f") present"
  else
    warn "missing $(basename "$f")"
  fi
done

# ── Kraken venv smoke ───────────────────────────────────────────────────────
echo "==KRAKEN_VENV=="
KENV="$SRC/../kraken-venv"
if [[ -x "$KENV/bin/ketos" ]]; then
  if "$KENV/bin/python" -c "import traceback" 2>/dev/null; then
    ok "kraken-venv python imports traceback"
  else
    fail "kraken-venv python broken (PYTHONPATH?)"
  fi
  if "$KENV/bin/python" -c "import matplotlib" 2>/dev/null; then
    ok "matplotlib import ok"
  else
    warn "matplotlib import fails — ketos train may crash (GLIBCXX)"
  fi
else
  fail "ketos missing at $KENV/bin/ketos"
fi

# ── historical-ocr venv ─────────────────────────────────────────────────────
echo "==HIST_VENV=="
HIST="/ocean/projects/hum260002p/sstrickland/historical-ocr"
if [[ -x "$HIST/.venv/bin/historical-ocr" ]]; then
  ok "historical-ocr CLI present"
else
  warn "historical-ocr venv missing — run sync_historical_ocr.sh"
fi

# ── Latest log tails ────────────────────────────────────────────────────────
echo "==LOGS=="
for pattern in htr-r6-core tess-pre1800 ibooks-ia; do
  log=$(ls -t "$SRC"/${pattern}-*.out 2>/dev/null | head -1 || true)
  if [[ -n "$log" && -f "$log" ]]; then
    echo "LOG|$pattern|$(basename "$log")|$(tail -3 "$log" | tr '\n' ' ')"
  fi
done

echo "==ISSUES==$issues"
EOS

OUT=$(ssh_cmd "SRC='$SRC' USER='$USER' bash -s" <<<"$REMOTE_SCRIPT" 2>&1) || {
  report "FAIL: remote check errored"
  echo "$OUT"
  exit 2
}

ISSUES=$(echo "$OUT" | grep '^==ISSUES==' | cut -d= -f2 || echo 1)

if [[ "$JSON" -eq 1 ]]; then
  python3 - <<'PY' "$OUT" "$ISSUES"
import json, sys
out, issues = sys.argv[1], int(sys.argv[2] or 0)
sections = {}
cur = "raw"
for line in out.splitlines():
    if line.startswith("==") and line.endswith("=="):
        cur = line.strip("=")
        sections[cur] = []
    else:
        sections.setdefault(cur, []).append(line)
print(json.dumps({"issues": issues, "sections": sections}, indent=2))
PY
else
  echo "$OUT"
  echo ""
  if [[ "${ISSUES:-0}" -gt 0 ]]; then
    report "RESULT: $ISSUES issue(s) — remediation may be needed"
  else
    report "RESULT: healthy / progressing"
  fi
fi

[[ "${ISSUES:-0}" -gt 0 ]] && exit 1
exit 0
