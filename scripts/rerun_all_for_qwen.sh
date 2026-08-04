#!/bin/bash
# Full corpus upgrade: correction + translation pass using qwen2.5vl:32b.
#
# Phase 1 — translate already-LLM-transcribed jobs that have no/partial translations.
#           translate_job.py skips pages with an existing _translation.txt.
#
# Phase 2 — correct HTR-only jobs (modelId=?): re-run lineation+HTR+LLM correction,
#           overwriting the raw Kraken YAML with a corrected one, then translate.
#           Uses --no-skip-successful to force the correction pass.
#
# Phase 3 — transcribe + correct + translate new computus manuscripts (no job yet).
#           Uses --skip-successful (idempotent after first run).
#
# Run in a detached screen:
#   screen -dmS rerun_all bash ~/Projects/transcription-shell/scripts/rerun_all_for_qwen.sh
set -euo pipefail

BASE=~/Projects/transcription-shell
TS=$BASE/.venv-lineation/bin/transcriber-shell
PY=$BASE/.venv-lineation/bin/python3
JOBS=/mnt/constantinople/seth/latin-ms-workspace/jobs
COMPUTUS=$BASE/references/computus-library/images
LOGS=$BASE/logs/rerun_qwen
mkdir -p "$LOGS"

PROVIDER=ollama
MODEL=qwen2.5vl:32b

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ─── helpers ────────────────────────────────────────────────────────────────

translate_job() {
    local job="$1"
    local dir="$JOBS/$job"
    [ -d "$dir" ] || { log "SKIP (no dir): $job"; return; }
    log "TRANSLATE $job"
    $PY "$BASE/scripts/translate_job.py" "$dir" \
        --provider "$PROVIDER" --model "$MODEL" \
        2>&1 | tee "$LOGS/translate_${job}.log"
    log "DONE translate $job"
}

correct_and_translate() {
    local job="$1"
    local imgdir="$JOBS/$job/01_pages_2500"
    local outdir="$JOBS/$job/03_artifacts_2500"
    [ -d "$imgdir" ] || { log "SKIP (no images): $job"; return; }
    log "CORRECT $job ($(ls $imgdir/*.jpg 2>/dev/null | wc -l) pages)"
    $TS batch \
        --provider "$PROVIDER" --model "$MODEL" \
        --llm-mode correct \
        --no-skip-successful \
        --output "$outdir" \
        "$imgdir" \
        2>&1 | tee "$LOGS/correct_${job}.log"
    log "DONE correct $job — now translating"
    translate_job "$job"
}

new_computus() {
    local name="$1"
    local imgdir
    imgdir=$(find "$COMPUTUS/$name" -name '*.jpg' -o -name '*.png' 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
    local count
    count=$(find "$COMPUTUS/$name" -name '*.jpg' -o -name '*.png' 2>/dev/null | wc -l)
    [ -z "$imgdir" ] || [ "$count" -lt 10 ] && { log "SKIP (too few images): $name"; return; }
    local outdir="$COMPUTUS/$name/03_artifacts"
    log "NEW COMPUTUS $name ($count images)"
    $TS batch \
        --doc-type computus_medieval_latin \
        --provider "$PROVIDER" --model "$MODEL" \
        --llm-mode correct \
        --translate \
        --skip-successful \
        --output "$outdir" \
        "$imgdir" \
        2>&1 | tee "$LOGS/new_${name}.log"
    log "DONE $name"
}

# ─── PHASE 1: translate already-LLM-transcribed jobs ───────────────────────
log "=== PHASE 1: TRANSLATION PASS ==="

# Fully untranslated, already LLM-quality transcriptions
for job in bl_harley_531 bsb_clm_4376 wellcome_3; do
    translate_job "$job"
done

# All other jobs — translate_job.py skips pages with existing _translation.txt
for job in \
    bnf_lat_2796_cod bnf_lat_4860_cod bnf_lat_7418 bnf_lat_894_cod \
    bodleian_ms_bodl_309 bsb_clm_14770 bsb_clm_18158 \
    einsiedeln_sbe_029 oxford_sjc_17 pal_lat_1407 \
    sb_110_cod sb_184_cod sb_250_cod sb_251_1 sb_251_2 \
    sb_682_cod sb_732_cod sb_878_cod sb_913_cod \
    wellcome_computistical_miscellany \
    bav_reg_lat_123 bav_reg_lat_141_cu1 \
    cambridge_cudl_ff_1_27 einsiedeln_sbe_029; do
    translate_job "$job"
done

# ─── PHASE 2: correct HTR-only jobs, then translate ────────────────────────
log "=== PHASE 2: CORRECTION PASS (HTR-ONLY JOBS) ==="

for job in \
    basel_ubb_an_iv_18 \
    basel_ubb_f_vii_12 \
    bav_pal_lat_1354 \
    bav_reg_lat_123 \
    bav_reg_lat_141_cu1 \
    bl_cotton_vitellius_a_xii \
    bl_royal_12_d_iv \
    bl_royal_13_a_xi \
    bnf_lat_894_cod \
    bsb_clm_14770 \
    bsb_clm_18158 \
    bsb_clm_4382 \
    cambridge_cudl_ff_1_27 \
    einsiedeln_sbe_029 \
    oxford_sjc_17 \
    sb_184_cod \
    sb_248_cod \
    sb_251_1 \
    sb_251_2 \
    sb_682_cod \
    sb_878_cod \
    sb_913_cod \
    wellcome_103; do
    correct_and_translate "$job"
done

# ─── PHASE 3: new computus manuscripts ─────────────────────────────────────
log "=== PHASE 3: NEW COMPUTUS MANUSCRIPTS ==="

for name in \
    BERN_BB_611_COD \
    BLB_AUG_PERG_229_COD \
    BLB_AUG_PERG_239_COD \
    BSB_CLM_14725_COD \
    DB_103_COD \
    SB_225_cod \
    SUBMSC_0046_cod; do
    new_computus "$name"
done

log "=== ALL PHASES COMPLETE ==="
