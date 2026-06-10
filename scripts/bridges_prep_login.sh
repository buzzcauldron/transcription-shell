#!/usr/bin/env bash
# DEPRECATED — login-node prep is unreliable and no longer needed.
# bridges_start.sh submits r6-core which runs prep inline on a GPU compute node.
# This file is kept only as a diagnostic emergency fallback.
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
cd "$SRC"
export SRC SKIP_BULLINGER_EXTRACT=1

# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
echo "[prep-login] done — submit training: bash $SRC/scripts/bridges_resubmit_training.sh"
