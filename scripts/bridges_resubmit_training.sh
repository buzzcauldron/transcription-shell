#!/usr/bin/env bash
# Deprecated wrapper — use bridges_start.sh instead.
#
# Old --train-only mode is now unnecessary: all sbatch jobs self-heal
# (r6-core does inline prep; anglicana + r7 depend on r6-core via afterok).
echo "[resubmit] redirecting to bridges_start.sh — see that script for usage"
exec "$(dirname "$0")/bridges_start.sh" "$@"
