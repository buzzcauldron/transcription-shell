#!/usr/bin/env bash
# Mac hop: tar-pipe control jobs Akdeniz → Bridges DTN, then sbatch on login.
# Akdeniz cannot SSH to PSC. Incomplete dest dirs are re-copied.
#
#   bash scripts/control_miscellany/pipe_control_jobs_akdeniz_to_bridges.sh
#   MAX_Q=8 bash scripts/control_miscellany/pipe_control_jobs_akdeniz_to_bridges.sh
set -u
LOG="${LOG:-/tmp/ctrl_bridges_sync.log}"
STAGE="${CTRL_SYNC_STAGE:-/tmp/ctrl_htr_stage}"
SRC="${CONTROL_JOBS_SRC:-/mnt/constantinople/seth/latin-ms-workspace/jobs_control_noncomputus}"
DEST="${CONTROL_JOBS_DEST:-/ocean/projects/hum260002p/sstrickland/control_miscellany_htr_jobs}"
SBATCH="${BRIDGES_CONTROL_HTR_SBATCH:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src/scripts/bridges_control_htr_job.sbatch}"
MAX_Q="${MAX_Q:-8}"
# -n on ssh in the job-id loop; rsync must NOT use -n (needs stdin).
SSH_OPTS=(-n -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -o ConnectTimeout=20)
RSYNC_SSH="ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -o ConnectTimeout=20"

jpg_count() {
  local host="$1" dir="$2" raw
  raw=$(ssh "${SSH_OPTS[@]}" "$host" \
    "find '$dir' -type f \\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.tif' -o -iname '*.png' \\) 2>/dev/null | wc -l") || true
  printf '%s\n' "$raw" | awk 'NF { print $NF }' | tail -1 | tr -cd '0-9'
  printf '\n'
}

complete_enough() {
  local jid="$1" src dst need
  src=$(jpg_count akdeniz "$SRC/$jid")
  dst=$(jpg_count bridges2 "$DEST/$jid")
  src=${src:-0}
  dst=${dst:-0}
  echo "[count] $jid src=$src dest=$dst"
  if [[ "$src" -lt 10 ]]; then
    if ssh "${SSH_OPTS[@]}" akdeniz "test -d '$SRC/$jid/00_sources_chunks' -o -d '$SRC/$jid/01_pages_2500'"; then
      echo "[WARN] $jid src=$src but image dir exists — will re-sync"
      return 1
    fi
    return 2
  fi
  need=$((src * 95 / 100))
  [[ "$dst" -ge "$need" ]] && [[ "$dst" -ge 10 ]]
}

sync_one() {
  local jid="$1"
  local stage="${STAGE}/$jid"
  mkdir -p "$stage"
  echo "[$(now)] rsync $jid akdeniz → stage"
  rsync -az --partial --info=stats1 \
    --exclude transcription_batches \
    --exclude 'logs/*.nohup.log' \
    -e "$RSYNC_SSH" \
    "akdeniz:$SRC/$jid/" "$stage/" || return 1
  echo "[$(now)] rsync $jid stage → ocean"
  ssh "${SSH_OPTS[@]}" bridges2 "mkdir -p '$DEST'" || true
  rsync -az --partial --info=stats1 \
    --exclude transcription_batches \
    --exclude 'logs/*.nohup.log' \
    -e "$RSYNC_SSH" \
    "$stage/" "bridges2-dtn:$DEST/$jid/" || return 1
  rm -rf "$stage"
}

ctrl_q() {
  ssh "${SSH_OPTS[@]}" bridges2 "squeue -u sstrickland -h -o '%j' | grep -c '^ctrl-' || true"
}

now() { date +%Y-%m-%dT%H:%M:%S%z; }

exec >>"$LOG" 2>&1
echo "==== START $(now) ===="

IDFILE="${CTRL_IDFILE:-/tmp/ctrl_job_ids.txt}"
ssh "${SSH_OPTS[@]}" akdeniz "ls -1 '$SRC'" >"${IDFILE}.raw" || true
grep '^ctrl_' "${IDFILE}.raw" >"$IDFILE" || true
id_n=$(wc -l <"$IDFILE" | tr -d ' ')
echo "id_count=$id_n"
n=0
ok=0
fail=0
while IFS= read -r jid <&3; do
  [[ -z "$jid" ]] && continue
  n=$((n + 1))
  if complete_enough "$jid"; then
    echo "[skip-tar] $jid already complete on ocean"
  else
    rc=$?
    if [[ "$rc" -eq 2 ]]; then
      echo "[SKIP] $jid — fewer than 10 source images"
      continue
    fi
    echo "[$(now)] re-sync $jid (incomplete or missing)"
    if sync_one "$jid"; then
      if complete_enough "$jid"; then
        ssh "${SSH_OPTS[@]}" akdeniz "mkdir -p '$SRC/$jid/status' && date -Iseconds > '$SRC/$jid/status/htr_bridges.CLAIMED'" || true
        echo "[$(now)] synced $jid"
      else
        echo "[FAIL] count mismatch after rsync $jid"
        fail=$((fail + 1))
        continue
      fi
    else
      echo "[FAIL] rsync $jid"
      fail=$((fail + 1))
      continue
    fi
  fi
  while true; do
    cq=$(ctrl_q | tail -1 | tr -d ' ')
    cq=${cq:-0}
    if [[ "$cq" -lt "$MAX_Q" ]]; then
      break
    fi
    echo "[throttle] ctrl queue=$cq sleep 180"
    sleep 180
  done
  sid=$(ssh "${SSH_OPTS[@]}" bridges2 "bash -lc '
    JOBS_ROOT=$DEST
    jid=$jid
    mkdir -p \"\$JOBS_ROOT/\$jid/status\" \"\$JOBS_ROOT/logs\"
    if [[ -f \"\$JOBS_ROOT/\$jid/status/htr_bridges.DONE\" ]]; then echo DONE; exit 0; fi
    if [[ -f \"\$JOBS_ROOT/\$jid/status/htr_bridges.SLURM\" ]]; then
      old=\$(cat \"\$JOBS_ROOT/\$jid/status/htr_bridges.SLURM\")
      if squeue -j \"\$old\" -h 2>/dev/null | grep -q .; then echo QUEUED \$old; exit 0; fi
    fi
    sid=\$(sbatch --parsable -A hum260002p --time=12:00:00 \
      --export=ALL,JOB_ID=\$jid,JOBS_ROOT=\$JOBS_ROOT \
      --job-name=ctrl-\${jid:5:12} $SBATCH)
    echo \"\$sid\" > \"\$JOBS_ROOT/\$jid/status/htr_bridges.SLURM\"
    echo \"\$sid\"
  '")
  echo "[sbatch] $jid $sid"
  ok=$((ok + 1))
done 3<"$IDFILE"
echo "==== END $(now) n=$n synced_or_queued=$ok fail=$fail ===="
