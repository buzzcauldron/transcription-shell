#!/usr/bin/env bash
# Push transcription-shell code to halxvi (the home GPU box).
#
# WHY THIS IS NOT `git pull` ON HALXVI: halxvi's ~/Projects/transcription-shell
# is NOT its own git repository. $HOME there is a checkout of a DIFFERENT repo
# (manuscript-fingerprint), so git commands run from the project directory
# resolve upward to $HOME/.git and report on the wrong repo entirely. Running
# `git pull` in that directory does not update this project; it touches
# manuscript-fingerprint. rsync is the only correct update path.
#
# WHY VIA AKDENIZ: halxvi has no public address. It maintains a reverse SSH
# tunnel to akdeniz, so akdeniz:127.0.0.1:2222 is the only route in, and the
# `halxvi` Host entry in akdeniz's ~/.ssh/config points there. That makes this a
# two-hop push: local -> akdeniz -> halxvi.
#
# NO --delete, deliberately: halxvi's /home runs near capacity and its project
# directory holds locally-produced artifacts and model files that exist nowhere
# else. A mirror-delete would discard them. Same rule as the Bridges sync.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
AKDENIZ="${AKDENIZ_HOST:-akdeniz}"
STAGE="${STAGE_DIR:-/tmp/tshell_halxvi_stage}"

# /usr/local/bin/rsync on this Mac is a stale x86_64 binary that shadows the
# working system one and dies with "Bad CPU type in executable". Resolve to a
# runnable rsync rather than trusting PATH order.
pick_rsync() {
  for c in /usr/bin/rsync "$(command -v rsync 2>/dev/null)" /opt/homebrew/bin/rsync; do
    [ -n "$c" ] && [ -x "$c" ] && "$c" --version >/dev/null 2>&1 && { echo "$c"; return; }
  done
  echo "no working rsync found" >&2; exit 1
}
RSYNC="${RSYNC:-$(pick_rsync)}"
echo "[rsync] using $RSYNC"
DEST="${HALXVI_REPO:-/home/sethj/Projects/transcription-shell}"

# Heavy directories are excluded rather than synced: they already exist on
# halxvi, they are large (references ~1.5G, vendor ~1.2G), and the disk there
# has little headroom. Code and scripts are what go stale.
EXCLUDES=(
  --exclude '.git/'
  --exclude '.venv/'
  --exclude '.venv-lineation/'
  --exclude '__pycache__/'
  --exclude '.pytest_cache/'
  --exclude 'references/'
  --exclude 'vendor/'
  --exclude 'artifacts/'
  --exclude 'output/'
  --exclude '*.mlmodel'
)

echo "[1/3] staging $REPO -> $AKDENIZ:$STAGE"
ssh -o BatchMode=yes "$AKDENIZ" "mkdir -p '$STAGE'" || exit 1
"$RSYNC" -az "${EXCLUDES[@]}" "$REPO/" "$AKDENIZ:$STAGE/" || exit 1

echo "[2/3] checking halxvi reachability and free space"
ssh -o BatchMode=yes "$AKDENIZ" \
  "ssh -o BatchMode=yes -o ConnectTimeout=10 halxvi 'df -h \$HOME | tail -1'" || {
    echo "halxvi unreachable -- is the reverse tunnel up? (expect a listener on akdeniz:2222)" >&2
    exit 1
  }

echo "[3/3] pushing $STAGE -> halxvi:$DEST"
ssh -o BatchMode=yes "$AKDENIZ" \
  "ssh -o BatchMode=yes halxvi 'mkdir -p $DEST' && rsync -az -e 'ssh -o BatchMode=yes' '$STAGE/' 'halxvi:$DEST/'" || exit 1

echo "[verify] src/ checksum comparison"
ssh -o BatchMode=yes "$AKDENIZ" \
  "ssh -o BatchMode=yes halxvi 'cd $DEST && find src scripts -type f -name \"*.py\" | wc -l'"
echo "done."
