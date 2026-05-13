#!/usr/bin/env bash
# Stage 0 — Convert: local images (TIF/BMP/WebP/etc.) → pipeline-ready JPEG in 01_pages/.
#
# Use this instead of s1_acquire.sh when images are already on disk (e.g. Dropbox TIFs).
#
# Usage:
#   bash s0_convert.sh --src /path/to/images/
#   bash s0_convert.sh --src /path/to/images/ --stem phillipps_10
#   LATIN_MS_JOB_ID=myjob LATIN_MS_SRC_DIR=/some/dir bash s0_convert.sh
#
# Options:
#   --src DIR       source directory (or LATIN_MS_SRC_DIR env var)
#   --stem STEM     if set, only convert files whose name contains STEM
#   --format jpeg   output format: jpeg (default) or png
#   --max-width N   resize long edge to N px (default: 3000)
#   --quality N     JPEG quality 1-95 (default: 90)
#   --force         overwrite existing outputs in 01_pages/
#   --dry-run       print what would happen without writing files
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
PAGES_DIR="${JOB_DIR}/01_pages"

SRC_DIR="${LATIN_MS_SRC_DIR:-}"
STEM_FILTER=""
FORMAT="${LATIN_MS_IMAGE_FORMAT:-jpeg}"
MAX_WIDTH="${LATIN_MS_IMAGE_MAX_WIDTH:-3000}"
QUALITY="${LATIN_MS_IMAGE_QUALITY:-90}"
FORCE_FLAG=""
DRY_FLAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --src)       SRC_DIR="$2";    shift 2 ;;
        --stem)      STEM_FILTER="$2"; shift 2 ;;
        --format)    FORMAT="$2";     shift 2 ;;
        --max-width) MAX_WIDTH="$2";  shift 2 ;;
        --quality)   QUALITY="$2";    shift 2 ;;
        --force)     FORCE_FLAG="--force"; shift ;;
        --dry-run)   DRY_FLAG="--dry-run"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

[[ -z "$SRC_DIR" ]] && {
    echo "ERROR: provide --src <dir> or set LATIN_MS_SRC_DIR" >&2
    exit 1
}
[[ ! -d "$SRC_DIR" ]] && { echo "ERROR: source directory not found: ${SRC_DIR}" >&2; exit 1; }

mkdir -p "$PAGES_DIR"

echo "========================================================"
echo "  Stage 0: image conversion"
echo "  Job:     ${LATIN_MS_JOB_ID}"
echo "  Source:  ${SRC_DIR}"
echo "  Output:  ${PAGES_DIR}"
echo "  Format:  ${FORMAT}  max-width=${MAX_WIDTH}  quality=${QUALITY}"
[[ -n "$STEM_FILTER" ]] && echo "  Filter:  *${STEM_FILTER}*"
echo "========================================================"

# Build source list: all images in SRC_DIR, optionally filtered by stem
if [[ -n "$STEM_FILTER" ]]; then
    # Collect matching files into a temp list
    TMPLIST=$(mktemp)
    find "$SRC_DIR" -maxdepth 2 \( \
        -iname "*.tif" -o -iname "*.tiff" -o -iname "*.bmp" -o \
        -iname "*.webp" -o -iname "*.jpg" -o -iname "*.jpeg" -o \
        -iname "*.png" -o -iname "*.gif" \
    \) | grep -i "$STEM_FILTER" > "$TMPLIST" || true

    if [[ ! -s "$TMPLIST" ]]; then
        echo "  No images matching '*${STEM_FILTER}*' found in ${SRC_DIR}"
        rm "$TMPLIST"
        exit 0
    fi

    # shellcheck disable=SC2046
    python3 "${SCRIPT_DIR}/convert_images.py" \
        $(cat "$TMPLIST") \
        --out-dir "$PAGES_DIR" \
        --format "$FORMAT" \
        --max-width "$MAX_WIDTH" \
        --quality "$QUALITY" \
        ${FORCE_FLAG} ${DRY_FLAG}
    rm "$TMPLIST"
else
    python3 "${SCRIPT_DIR}/convert_images.py" \
        "$SRC_DIR" \
        --out-dir "$PAGES_DIR" \
        --format "$FORMAT" \
        --max-width "$MAX_WIDTH" \
        --quality "$QUALITY" \
        ${FORCE_FLAG} ${DRY_FLAG}
fi

if [[ -z "$DRY_FLAG" ]]; then
    PAGE_COUNT=$(find "$PAGES_DIR" -maxdepth 1 \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \) | wc -l | tr -d ' ')
    echo ""
    echo "==> Stage 0 done: ${PAGE_COUNT} image(s) ready in ${PAGES_DIR}"
    echo "    Next: bash s3_lineate.sh  or  bash s4_transcribe.sh"
fi
