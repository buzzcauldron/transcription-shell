#!/usr/bin/env bash
# Extract Latin transcription text from all computus jobs and run run_stylo_target.R.
# Run on akdeniz: screen -dmS batch_stylo bash ~/scripts/batch_stylo_computus.sh

set -euo pipefail

JOBS=~/latin-ms-workspace/jobs
STYLO_SCRIPTS=~/Projects/stylometry-r/scripts
STYLO_OUT=~/Projects/stylometry-r/output
REF=~/Projects/stylometry-r/output/de_luce_r_rescore/reference_set_medieval_mixed
TSHELL=~/Projects/transcription-shell
EXTRACT_PY="$TSHELL/scripts/extract_ms_text.py"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

JOBS_LIST=(
  bsb_clm_14770 bsb_clm_18158 cambridge_cudl_ff_1_27 bodleian_ms_bodl_309
  bnf_lat_7418 bnf_lat_2796_cod bnf_lat_4860_cod bnf_lat_894_cod
  bl_royal_12_d_iv bl_royal_13_a_xi bl_cotton_vitellius_a_xii
  wellcome_computistical_miscellany einsiedeln_sbe_029
  sb_110_cod sb_184_cod sb_248_cod sb_250_cod sb_251_1
  sb_682_cod sb_732_cod sb_878_cod sb_913_cod
  basel_ubb_an_iv_18 basel_ubb_f_vii_12
  bav_pal_lat_1354 bav_reg_lat_123 bav_reg_lat_141_cu1
  oxford_sjc_17 pal_lat_1407
)

mkdir -p "$STYLO_OUT/batch_stylo_texts"

# Shared output dir so the reference corpus cache is built once and reused
SHARED_OUT="$STYLO_OUT/computus_batch_stylo"
mkdir -p "$SHARED_OUT"

for job in "${JOBS_LIST[@]}"; do
  artifacts="$JOBS/$job/03_artifacts_2500"
  [[ -d "$artifacts" ]] || { log "$job: no artifacts dir — skip"; continue; }

  yaml_count=$(find "$artifacts" -name "*_transcription.yaml" 2>/dev/null | wc -l)
  [[ $yaml_count -eq 0 ]] && { log "$job: no transcription YAMLs — skip"; continue; }

  # Extract Latin text
  txt_out="$STYLO_OUT/batch_stylo_texts/${job}_latin.txt"
  log "$job: extracting $yaml_count YAMLs → $txt_out"
  python3 "$EXTRACT_PY" "$artifacts" "$txt_out"

  wc_words=$(wc -w < "$txt_out" 2>/dev/null || echo 0)
  [[ $wc_words -lt 100 ]] && { log "$job: too few words ($wc_words) — skip"; continue; }
  log "$job: $wc_words words"

  # Per-manuscript result directory
  ms_out="$STYLO_OUT/${job}_r_stylo"
  mkdir -p "$ms_out"

  log "$job: running stylo (REF=$REF)"
  Rscript "$STYLO_SCRIPTS/run_stylo_target.R" \
    "$txt_out" "$ms_out" "$job" "$REF" \
    2>&1 | tee "$ms_out/stylo.log" | grep -E "^\[|genre|tradition|Delta|DONE|ERROR" || true

  log "$job: done → $ms_out"
done

log "All stylo runs complete."
