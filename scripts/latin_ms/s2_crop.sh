#!/usr/bin/env bash
# Stage 2 — Crop/normalize: rename raw strigil images to the pipeline naming
# convention and normalize to JPEG.
#
# Naming: {MSID}_f{NNN}{r|v}.jpg  (NNN = zero-padded folio number)
# Images in 00_sources/ are taken in filename sort order; folio numbering
# starts at LATIN_MS_FOLIO_START (default 1), first side = LATIN_MS_FIRST_SIDE.
#
# Usage:  s2_crop.sh
# Optional: set LATIN_MS_MAX_LONG_EDGE in env to resize (0 = no resize).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
SRC_DIR="${JOB_DIR}/00_sources"
DST_DIR="${JOB_DIR}/01_pages"
mkdir -p "$DST_DIR"

MSID="${LATIN_MS_MSID}"
FOLIO="${LATIN_MS_FOLIO_START:-1}"
FIRST_SIDE="${LATIN_MS_FIRST_SIDE:-r}"
QUALITY="${LATIN_MS_JPEG_QUALITY:-92}"
MAX_EDGE="${LATIN_MS_MAX_LONG_EDGE:-0}"

SIDE="$FIRST_SIDE"
COUNT=0

mapfile -t IMAGES < <(find "$SRC_DIR" -maxdepth 2 \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tif" -o -iname "*.tiff" \) | sort)

if [[ ${#IMAGES[@]} -eq 0 ]]; then
    echo "ERROR: no images found in ${SRC_DIR}" >&2
    exit 1
fi

echo "==> Stage 2: normalizing ${#IMAGES[@]} image(s) → ${DST_DIR}"

for SRC in "${IMAGES[@]}"; do
    FOLIO_PAD=$(printf "%03d" "$FOLIO")
    DEST="${DST_DIR}/${MSID}_f${FOLIO_PAD}${SIDE}.jpg"

    if command -v convert &>/dev/null; then
        # ImageMagick path
        if [[ "$MAX_EDGE" -gt 0 ]]; then
            convert "$SRC" -resize "${MAX_EDGE}x${MAX_EDGE}>" -quality "$QUALITY" "$DEST"
        else
            convert "$SRC" -quality "$QUALITY" "$DEST"
        fi
    elif command -v sips &>/dev/null; then
        # macOS fallback (sips ignores quality arg; use for PNG→JPEG at least)
        sips -s format jpeg --out "$DEST" "$SRC" >/dev/null
        if [[ "$MAX_EDGE" -gt 0 ]]; then
            sips -Z "$MAX_EDGE" "$DEST" >/dev/null
        fi
    else
        echo "ERROR: neither 'convert' (ImageMagick) nor 'sips' found." >&2
        exit 1
    fi

    echo "  ${SRC##*/} → ${DEST##*/}"
    COUNT=$((COUNT + 1))

    # Advance folio/side
    if [[ "$SIDE" == "r" ]]; then
        SIDE="v"
    else
        SIDE="r"
        FOLIO=$((FOLIO + 1))
    fi
done

echo "==> Stage 2 done: ${COUNT} page(s) written to ${DST_DIR}"
echo "    Review names and adjust any mislabeled folios before proceeding."
