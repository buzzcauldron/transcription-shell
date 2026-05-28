#!/usr/bin/env bash
# Acquire page images for computus-library entries that have archive_ms_page URLs.
# Uses strigil (IIIF / Gallica / BL / Internet Archive / Wellcome, etc.).
#
# Usage:
#   acquire_library.sh              # all strigil_acquire=true with archive_ms_page
#   acquire_library.sh BNF_LAT_2796_COD
#   acquire_library.sh --dry-run
#
# Output: references/computus-library/images/<id>/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST="${REPO_ROOT}/references/computus-library/manifest.json"
IMG_ROOT="${REPO_ROOT}/references/computus-library/images"
PLANNER="${SCRIPT_DIR}/_acquire_plan.py"

DRY_RUN=0
IDS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,11p' "$0"
      exit 0
      ;;
    *) IDS+=("$arg") ;;
  esac
done

if ! command -v strigil >/dev/null 2>&1; then
  echo "ERROR: strigil not on PATH. Install: pip install -e ~/Projects/strigil" >&2
  exit 1
fi

if [[ ! -f "$MANIFEST" ]]; then
  echo "ERROR: missing ${MANIFEST}. Run: python3 scripts/computus/crawl_citca_catalogue.py" >&2
  exit 1
fi

plan_args=("$MANIFEST")
if [[ ${#IDS[@]} -gt 0 ]]; then
  plan_args+=("${IDS[@]}")
fi

while IFS='|' read -r id url flags kind; do
  if [[ "$kind" == "local" ]]; then
    echo "==> ${id}: skip (local images at ${url})"
    continue
  fi
  out="${IMG_ROOT}/${id}"
  mkdir -p "$out"
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "==> ${id}: strigil ${flags} --url ${url} --out-dir ${out}"
    continue
  fi
  echo "==> ${id}: strigil → ${out}"
  # shellcheck disable=SC2086
  strigil --url "$url" --out-dir "$out" --min-image-size 200k --no-progress ${flags} \
    ${STRIGIL_FLAGS:-} || echo "WARN: strigil failed for ${id}" >&2
done < <(python3 "$PLANNER" "${plan_args[@]}")

echo "Done. Images under ${IMG_ROOT}/"
