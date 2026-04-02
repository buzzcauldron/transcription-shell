# Plan (prioritized checklist)

Edit priorities as needed. Check items off when done. Prefer recording **done** work in [progress.md](progress.md) and non-obvious choices in [decisions.md](decisions.md).

## Active campaign — Vatlib Pal.lat.1447 segtrain + transcription (2026-04)

### Segtrain pipeline (server: seth@akdeniz.lan.cmu.edu, RTX 4090)
- [x] Install Kraken in `~/.venv-kraken` (Python 3.12); base model `model_249.mlmodel`
- [x] Round 0 complete — `kraken-round0.mlmodel_best.mlmodel` saved
- [x] Round 1 complete — 50 epochs, `_49` checkpoint (no `_best` saved — investigate)
- [ ] Round 2 in progress — monitor via `segtrain-20260401-2037.log`
- [ ] Rounds 3–4 pending — auto-resumes via `~/run.sh`
- [ ] After all rounds: run `ketos test` on held-out GT; time inference per folio; compare rounds

### GT scraping + annotation pipeline (local)
- [x] Strigil IIIF filename collision bug fixed (`storage.py` `_iiif_identifier_from_parts()`)
- [x] 13 Pal.lat.1447 folios scraped → `strigil/output/digi.vatlib.it/images/`
- [x] Glyph Machina baselines run → `artifacts/gm-vatlib-palat1447-*/lines.xml` (13 XMLs)
- [x] GT assembled + synced to server → `~/kraken-vatlib-gt/` (423 images, 441 XMLs)
- [ ] Scrape additional vatlib folios post-training for expanded eval set

### LLM transcription pipeline (local)
- [x] Prompt config: `artifacts/prompt-vatlib-palat1447.yaml` (Carolingian Latin, 800–900 CE)
- [x] Gemini 2.0 Flash — all 13 folios transcribed
- [ ] Ollama llava:latest — batch in progress (PID 32604, `transcription-ollama-20260401-2036.log`)
  - Known issue: llava returns markdown-fenced YAML (`\`\`\`yaml`) and uses `|` in string values → parse failures on first 2 folios; transcriptions saved despite errors
- [ ] Compare Gemini vs llava output: accuracy, confidence, uncertainty token rate, speed/folio
- [ ] Evaluate llava as offline/free alternative for future pipeline versions

### Server → local transcription trigger
- [ ] After each training round: rsync new `_best.mlmodel` to `artifacts/models/`
- [ ] Rsync batches of server GT images + XMLs → local `artifacts/server-gt/`
- [ ] Run `transcriber-shell run --skip-gm` on unprocessed images (Gemini, batched)
- [ ] Server check cron active — job `9fd6d89d`, every 30 min

### Model evaluation (post-training)
- [ ] `ketos test -m kraken-roundN.mlmodel_best.mlmodel` on 10% held-out GT
- [ ] Compare: val_mean_iu across rounds (round 0 baseline ~0.53)
- [ ] Time `kraken segment` per folio at each checkpoint
- [ ] Pick best accuracy/speed tradeoff for production default

---

## High priority

- [ ] Keep [architecture.md](architecture.md) as the single doc for pipeline diagram + prose (avoid duplicating a second `ARCHITECTURE.md` on case-insensitive filesystems).

## Medium priority

- [ ] When HTTP API and CLI behavior diverge, update [TDAD_DESIGN_REVIEW.md](TDAD_DESIGN_REVIEW.md) if the TDAD graph is meant to reflect policy, and add a row to [decisions.md](decisions.md).

## Low priority / nice-to-have

- [ ] Regenerate or extend `.tdad/workflows/` JSON when major pipeline stages or API routes change (optional; TDAD is descriptive).

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
