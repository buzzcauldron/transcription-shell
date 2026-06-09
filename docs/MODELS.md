# Models & training

This document describes the **segmentation and handwritten-text-recognition (HTR) models** used by `transcription-shell`, how they were trained, and how to reproduce or run them. It is modeled on the [`glyph_machina_public`](https://github.com/buzzcauldron/glyph_machina_public) reproduction repo (*"Democratizing the medieval English legal tradition"*), extended from medieval English legal hands to a broader **Latin** program: Carolingian computus, medieval/early-modern Latin documents, and continental charters.

The pipeline is **lineation → HTR → LLM**: a Kraken baseline-segmentation model finds text lines, a Kraken HTR model produces a draft transcription, and an LLM (via the [Academic Handwriting Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol)) produces the final structured diplomatic transcription. The models here cover the first two stages; the LLM stage is configured per document type (see [`scripts/latin_ms/document_types/`](../scripts/latin_ms/document_types/)).

> **Note on accuracy.** As in the Glyph Machina repo, the models that ship with a given round are not the last word: each round trains on more data and improves on the previous one. The numbers below are **validation** character/word accuracy reported by `ketos` (CER/WER shown as `1 − accuracy`), **not** held-out test scores with KenLM decoding — so they are not directly comparable to the 4.9 % CER / 15.5 % WER headline figure in the Glyph Machina paper. Per-corpus CER on a frozen test set is computed separately with `transcriber-shell score-htr-per-corpus`.

## Models

All models are Kraken VGSL `.mlmodel` files trained on **akdeniz** (RTX 4090). The registry that maps document types to models lives in [`scripts/latin_ms/document_types/models/`](../scripts/latin_ms/document_types/models/) (one YAML per model).

### HTR (recognition)

| Model | Target | Base | Round | Train / val lines | Val char acc (≈CER) | Val word acc (≈WER) |
|-------|--------|------|-------|-------------------|---------------------|---------------------|
| `gm-htr-r2_best` | Latin/French/English, medieval + early-modern (anglicana, gothic cursiva/textura, humanist italic) | `gm-hf-htr_best` | 2 | trimmed | 0.841 (≈15.9 %) | 0.522 (≈47.8 %) |
| `gm-htr-computus_best` | **Caroline minuscule computus & astronomy, 6th–11th c.** | `gm-htr-r2_best` | c1 | 185,307 / 9,753 | **0.9434 (≈5.7 %)** | 0.759 (≈24.1 %) |
| `gm-htr-r5-best` | **Broad Carolingian/medieval Latin** (caroline, proto-/pre-gothic, insular) | `gm-htr-r2_best` | 5 | 290,414 / 15,285 | 0.9289 → 0.932* (≈6.8 %) | 0.737 → 0.748* | 
| `gm-hf-htr_best` | Hugging Face transfer-learned base (seed for r2) | — | hf | — | — | — |

\* `gm-htr-r5-best.mlmodel` is the **epoch-22** checkpoint exported on 2026-06-02 (val 0.9289). Training was later **resumed and is ongoing** on akdeniz; the live best checkpoint is **epoch 39, val 0.9320** (`gm-htr-r5/checkpoint_39-0.9320.ckpt`). Re-export and refresh this table when the run early-stops.

**Which HTR model when:** use `gm-htr-computus_best` for computus / Caroline-minuscule pages (it beats r2 by **+10.2 pp** char accuracy there); use `gm-htr-r5-best` for diverse or non-computus Latin; `gm-htr-r2_best` remains the general medieval/early-modern default and the base both specialists were fine-tuned from.

### Segmentation (baseline detection)

| Model | Target | Notes |
|-------|--------|-------|
| `kraken-merged-seg_best` | merged multi-corpus baseline segmentation | current default seg model (4.9 MB) |
| `gm-seg` | Glyph Machina segmentation export | alternate |

Earlier incremental rounds (`kraken-round0…3`, `kraken-son-of-gm`, `kraken-finetuned_*`) are retained on akdeniz but superseded by `kraken-merged-seg_best`.

## Document-type routing

Each document type ([`scripts/latin_ms/document_types/*.yaml`](../scripts/latin_ms/document_types/)) names a prompt, an HTR model, a segmentation model, and LLM provider defaults. The registry selector (`src/transcriber_shell/htr/model_registry.py`) can also resolve a model by **language + era + script** when no exact name is given.

| Document type | HTR model | Prompt |
|---------------|-----------|--------|
| `computus_medieval_latin` | `gm-htr-computus_best` | `prompt_computus.yaml` |
| `medieval_latin_charter` | `gm-htr-r2_best` | `prompt_charter.yaml` |
| `medieval_latin_legal` | `htr_latin_updated_best` | `prompt_latin.yaml` |
| `early_modern_latin` | `gm-htr-r2_best` | `prompt_latin.yaml` |
| `medieval_latin_ecclesiastical` | `Tridis_Medieval_EarlyModern` | `prompt_ecclesiastical.yaml` *(TODO)* |
| `early_modern_english` | `transfer_learned_1k_lines` | `prompt_secretary.yaml` *(TODO)* |

## Training corpora

HTR/seg models are trained from **PageXML** corpora (page image + `*.xml` line baselines + transcriptions). Download and citations: [`scripts/download_htr_corpora.sh`](../scripts/download_htr_corpora.sh) and [`scripts/htr_corpora.bib`](../scripts/htr_corpora.bib).

Corpora used across rounds include: **CATMuS-Medieval**, **TRIDIS**, **HIMANIS**, **CREMMA** (medieval / medieval-lat / early-modern), **Königsfelden charters**, **caroline-minuscule**, **carolingian-latin-2025 / -vienna**, **ANR-ENDP**, **Eutyches**, **Boccace**, **HTRomance** (French/Italian/Latin/Spanish), **iForal**, **ONB Cod. 940**, **Paris Bible**, **OCR-D GT**, and **transcriboQuest-2024**.

Only PageXML pairs enter the manifests. Line-image+text datasets (e.g. **bullinger-htr**) and non-transcription datasets (e.g. the **MPS** handwriting-*dating* set) are **not** used by this pipeline.

## Dependencies

Training and inference use **Kraken 7** (`ketos`), in contrast to the Kraken 6 pipeline in `glyph_machina_public`. Confirmed working stack on akdeniz:

- `kraken` / `ketos` **7.0.2**
- `torch` **2.10.0+cu128**, `lightning`, `torchmetrics`
- `pandas`, `Pillow`; optional `pyctcdecode` + **KenLM** for LM decoding

For the surrounding pipeline (lineation glue, LLM, validators), install the package extras (see the top-level [README](../README.md)):

```bash
pip install -e ".[api,gemini,xml-xsd,kraken,pdf]"
```

> **PyTorch 2.6+ resume gotcha.** `ckpt_path` resume can fail with `UnpicklingError` because Lightning loads checkpoints with `weights_only=True`. Patch the venv's `lightning/fabric/plugins/io/torch_io.py` so `weights_only` defaults to `False` (a trusted local checkpoint), then resume normally.

## Training

All training runs unprivileged (no `sudo`) on the lab GPU. The general loop is **prepare manifest → `ketos … train` → export best `.mlmodel`**.

### Segmentation

```bash
# Build PageXML train/test split, then run incremental segtrain rounds.
python scripts/prepare_kraken_segtrain.py        # assembles PageXML into round dirs
bash   scripts/latin_ms/patch_kraken_segtrain.sh # optional: expose threshold/min_length
python scripts/segtrain_rounds.py --start-round 0
```

`ketos segtrain` starts from a pretrained `blla` backbone and trains on the PageXML in the round directories. Choose the checkpoint that maximizes `val_mean_iu` (without a terrible `val_freq_iu`) and export it as the round's `_best.mlmodel`.

### HTR

```bash
# 1) Build line manifests from PageXML corpora
python scripts/prepare_computus_htr_train.py     # → computus-gt/{train,val}_manifest.txt
#    (or scripts/prepare_hf_htr_train.py for the broad set)

# 2) Fine-tune from a base model on akdeniz (RTX 4090)
ketos -d cuda:0 --workers 4 --precision bf16-mixed train \
  --resume <base_or_checkpoint>.ckpt \
  --resize union -f page -q early \
  --lag 20 --min-epochs 5 -N 100 -B 16 \
  -r 0.00001 --schedule cosine --augment \
  -t computus-gt/train_manifest.txt -e computus-gt/val_manifest.txt \
  -o gm-htr-computus
```

Helper scripts: [`scripts/train_computus_htr.sh`](../scripts/train_computus_htr.sh), [`scripts/htr_train_cmu.sh`](../scripts/htr_train_cmu.sh) (launch over SSH), [`scripts/watch_training.sh`](../scripts/watch_training.sh) (monitor), [`scripts/resume-lineation-training.sh`](../scripts/resume-lineation-training.sh), and [`scripts/wait_and_copy_htr_model.sh`](../scripts/wait_and_copy_htr_model.sh) (export the best checkpoint when the run ends).

Hyperparameters used for the specialists (computus c1, r5): base = `gm-htr-r2_best`, batch 16, cosine schedule, LR 1e-5, `bf16-mixed`, augmentation on, early-stop lag 20, up to 100 epochs.

## Running end-to-end

Where `glyph_machina_public` chains `run_segmenter.py → run_line_image_generator.py → run_htr.py → run_gemini.py`, `transcription-shell` runs the whole lineation → HTR → LLM pipeline in one command:

```bash
# Single page
transcriber-shell run \
  --job-id mypage --image page.jpg \
  --doc-type computus_medieval_latin \
  --lineation-backend kraken \
  --htr-combination kraken_htr \
  --provider gemini --model gemini-2.5-flash

# A folder or PDF (PDFs are rasterised per page)
transcriber-shell batch scans/ \
  --doc-type medieval_latin_charter \
  --lineation-backend kraken --htr-combination kraken_htr \
  --batch-report report.json
```

Outputs: `artifacts/<job_id>/lines.xml` (PageXML baselines) and `artifacts/<job_id>/<stem>_transcription.yaml` (protocol-validated diplomatic transcription). List available models with `transcriber-shell list-htr-models`.

## Credits & attribution

- **Glyph Machina** — pipeline design, base recognition model, and the [`glyph_machina_public`](https://github.com/buzzcauldron/glyph_machina_public) reproduction repo this is modeled on (paper: *Democratizing the medieval English legal tradition*; training data from the [AALT](https://aalt.law.uh.edu/)).
- **Kraken** — [mittagessen/kraken](https://github.com/mittagessen/kraken) baseline segmentation + recognition (`ketos`).
- **latin_documents** — [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents) lineation/training data and baseline tooling.
- **Training corpora** — CATMuS-Medieval, TRIDIS, HIMANIS, CREMMA, Königsfelden, HTRomance, and others; see [`scripts/htr_corpora.bib`](../scripts/htr_corpora.bib) for full citations.
- **Transcription protocol** — [buzzcauldron/transcription-protocol](https://github.com/buzzcauldron/transcription-protocol) for the LLM stage.
