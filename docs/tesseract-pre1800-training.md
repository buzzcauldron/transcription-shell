# Tesseract fine-tuning for pre-1800 print OCR

Transcriber-shell runs **in-process Tesseract** (`tesseract_htr`) for speed. Training and tesstrain orchestration live in the sibling **[historical-ocr](https://github.com/buzzcauldron/historical-ocr)** project; this repo owns **GT4HistOCR corpus prep** only.

## Division of labour

| Step | Owner | What |
|------|-------|------|
| Download GT4HistOCR | transcription-shell | `scripts/download_htr_corpora.sh` |
| Line PNG + `.gt.txt` | transcription-shell | `scripts/prepare_tesseract_ocr_corpus.py` |
| `make training` + `traineddata` | **historical-ocr** | `historical-ocr tess train-gt` |
| Inference preprocess stacks | historical-ocr | `document_types/print/models/*.yaml`, `ocr/preprocess.py` |
| Runtime in shell | transcription-shell | `tesseract_htr.py` + optional `htr/tesseract_finetune.py` |

## Prerequisites

```bash
# 1. Sibling checkout
cd ~/Projects
git clone git@github.com:buzzcauldron/historical-ocr.git "historical ocr"
cd "historical ocr" && pip install -e .

# 2. Corpora (4 GB GT4HistOCR)
cd ~/Projects/transcription-shell
SKIP_LARGE=0 ./scripts/download_htr_corpora.sh

# 3. System Tesseract + script models
brew install tesseract tesseract-lang   # macOS; provides tessdata_best/script/Fraktur.traineddata
```

## Quick start

```bash
./scripts/train_tesseract_pre1800.sh all
```

This runs:

1. `prepare_tesseract_ocr_corpus.py --profile pre1800` → `~/src/tesseract-pre1800-gt/ground-truth/`
2. `historical-ocr tess train-gt` → `~/Projects/historical ocr/models/lat_pre1800.traineddata`

Override paths:

```bash
export HISTORICAL_OCR_ROOT="$HOME/Projects/historical ocr"
export HTR_CORPORA_ROOT="$HOME/src/htr-corpora"
export TESS_GT_DIR="$HOME/src/tesseract-pre1800-gt"
export MAX_ITERATIONS=500000
./scripts/train_tesseract_pre1800.sh train
```

## Use the trained model

```bash
export TESSDATA_PREFIX=~/Projects/historical\ ocr/models/tessdata
export TRANSCRIBER_SHELL_TESSERACT_LANG=lat_pre1800
export TRANSCRIBER_SHELL_TESSERACT_ENABLED=true
export TRANSCRIBER_SHELL_HTR_COMBINATION=tesseract_htr

transcriber-shell run --doc-type early_modern_latin --image page.jpg --prompt …
```

Or copy `lat_pre1800.traineddata` into any `tessdata/` dir and set `TESSDATA_PREFIX`.

**Borrow inference settings** from historical-ocr print profiles (`lat+frk+eng`, invert+contrast) via `TRANSCRIBER_SHELL_HTR_PREPROCESS_*` — see [latin-documents-training-data.md](latin-documents-training-data.md).

## Bridges (PSC)

CPU job (no GPU):

```bash
sbatch scripts/bridges_train_tesseract_pre1800.sbatch
```

Set `TRANSCRIBER_SHELL_ROOT`, `HISTORICAL_OCR_ROOT`, `HTR_CORPORA_ROOT` in the job environment if paths differ on Ocean.

## Pre-1800 corpus bundle

See `scripts/tesseract_ocr_corpus_registry.yaml` and `pre1800_default` in historical-ocr’s `tesseract_train_sources.yaml`.

## Skip local training

- [frak2021](https://ub-backup.bib.uni-mannheim.de/~stweil/tesstrain/frak2021/) — Mannheim Fraktur models
- historical-ocr `histnews.traineddata` — 18th–20th c. newspapers (different task)

## References

- [tesstrain GT4HistOCR wiki](https://github.com/tesseract-ocr/tesstrain/wiki/GT4HistOCR)
- historical-ocr `docs/PRINT_OCR.md`, `docs/ECOSYSTEM.md`
