#!/usr/bin/env bash
# Stage 1 — Acquire: pull page images from institutional sources via strigil.
# Usage:  s1_acquire.sh [URL ...]
#   If URLs are passed on the command line they override $LATIN_MS_SOURCES.
#   Output lands in $JOB_DIR/00_sources/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
OUT_DIR="${JOB_DIR}/00_sources"
mkdir -p "$OUT_DIR"

URLS="${*:-${LATIN_MS_SOURCES:-}}"
if [[ -z "$URLS" ]]; then
    echo "ERROR: no URLs provided. Pass them as arguments or set LATIN_MS_SOURCES." >&2
    exit 1
fi

echo "==> Stage 1: strigil → ${OUT_DIR}"
# shellcheck disable=SC2086
strigil --url $URLS \
    --out-dir "$OUT_DIR" \
    --min-image-size 200k \
    --no-progress \
    ${STRIGIL_FLAGS:-}

IMAGE_COUNT=$(find "$OUT_DIR" -maxdepth 2 -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tif" -o -iname "*.tiff" | wc -l | tr -d ' ')
echo "==> Stage 1 done: ${IMAGE_COUNT} image(s) in ${OUT_DIR}"
