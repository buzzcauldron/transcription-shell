# Training data: [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents) (`data/`)

**transcriber-shell** consumes a trained model through **`TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE`** and **`TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH`** (see [mask-lineation-plugin.md](mask-lineation-plugin.md)). Training is **not** in the core package, but this repo includes an optional **MVP trainer** ([`examples/latin_lineation_mvp`](../examples/latin_lineation_mvp/README.md)) that learns from **latin_documents** `data/` and exports a **`predict_masks`**-compatible checkpoint.

## What is in `data/`

After cloning [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents), the [`data/`](https://github.com/ideasrule/latin_documents/tree/master/data) directory holds **paired** assets per manuscript page:

| File | Role |
|------|------|
| `*.jpg` | Full page scan |
| `*.xml` | PageXML with regions / **TextLine** / **Baseline** (`points="x,y ..."`) aligned to that image |

That pairing is the usual supervision for **line detection** or **mask** models: rasterize baselines or regions into per-line masks, or sample patches, using the same filenames (stem) for image and XML.

## Other training-related files in the repo (same clone)

- **`train_line_list.csv`** / **`val_line_list.csv`** — line-image paths under `data/` plus transcription text (geared toward **line OCR / LM** training, not full-page lineation).
- **`run_segmenter.py`** — example **Kraken BLLA** segmentation with a VGSL model (see comments and **`pipeline.sh`** for the upstream Kraken fork note).
- Notebooks (`Train with lightning.ipynb`, `train_transformer.ipynb`, etc.) — experiments in the upstream repo, not invoked by transcriber-shell.

## MVP trainer and GM benchmark (this repo)

| Artifact | Purpose |
|----------|---------|
| [`examples/latin_lineation_mvp`](../examples/latin_lineation_mvp/README.md) | `latin-lineation-train` on `data/*.jpg` + `data/*.xml`; **`latin_lineation_mvp.infer:predict_masks`** |
| [`scripts/benchmark_gm_parity.py`](../scripts/benchmark_gm_parity.py) | Compare reference vs hypothesis PageXML (same metrics as `compare-lines-xml`) |

After training, tune **`TRANSCRIBER_SHELL_MASK_THRESHOLD`** and **`TRANSCRIBER_SHELL_MASK_BASELINE_SMOOTH_WINDOW`**; see [`.env.example`](../.env.example).

## Suggested workflow

1. **Clone** the dataset (shallow is enough for `data/`):

   ```bash
   ./scripts/clone-latin-documents.sh
   ```

   Or set **`LATIN_DOCUMENTS_ROOT`** (optional) to an existing checkout; see [`.env.example`](../.env.example).

2. **Train** with **`latin_lineation_mvp`** (see its README), the convenience wrapper **`python scripts/train_local_mask_lineation.py`** (resolves `LATIN_DOCUMENTS_DATA` / `LATIN_DOCUMENTS_ROOT` like the shell script), or your own code on `data/*.jpg` + `data/*.xml`. Outputs must match [mask-lineation-plugin.md](mask-lineation-plugin.md): **`(L, H, W)`** float masks.

3. **Point transcriber-shell** at **`latin_lineation_mvp.infer:predict_masks`** (or your module) and the **`.pt`** checkpoint path.

4. **Optional:** compare to Glyph Machina using `transcriber-shell compare-lines-xml` or **`scripts/benchmark_gm_parity.py`** ([README](../README.md)).

## Tuned-model registry

Per-tuned-model YAMLs live in [`scripts/latin_ms/document_types/models/`](../scripts/latin_ms/document_types/models/) — one file per trained HTR or segmentation checkpoint. Each spec declares the languages, eras, and scripts the model covers, plus its training round and metrics. The selector ([`src/transcriber_shell/htr/model_registry.py`](../src/transcriber_shell/htr/model_registry.py)) ranks candidates by (criteria coverage, language match, era match, training round, best CER) so the highest-quality applicable model wins automatically.

```bash
# See everything on disk:
transcriber-shell list-htr-models

# Pin a specific model for a run (overrides --doc-type's pick + the env var):
transcriber-shell run --htr-model gm-htr-r2_best --image page.jpg --prompt …

# Score a model per-corpus to populate metrics.per_corpus_cer in its YAML:
transcriber-shell score-htr-per-corpus \
    --model gm-htr-r2_best \
    --eval-dir ~/eval_corpora/ \
    --update-registry
```

Doc-type specs can pick a registry model by name (`htr.model: gm-htr-r2_best`) or leave both `model:` and `path:` empty to let the registry's selector resolve via the doc-type's own (language, era, script) — that's how `early_modern_latin.yaml` picks up `gm-htr-r2_best` and `kraken-merged-seg_best` without hardcoding paths.

### Adding a newly trained model

1. Train (e.g. ketos on the 3080 / CMU GPU). Save the `_best.mlmodel` under `~/src/latin_documents/`.
2. Drop a YAML next to the existing registry files. The README in that folder has the schema; key fields are `name`, `kind`, `path`, `languages`, `eras`, `scripts`, and a `training` block with the hyperparameters that produced the checkpoint.
3. Run `transcriber-shell score-htr-per-corpus --model NAME --eval-dir … --update-registry` so the spec's `metrics.per_corpus_cer` reflects reality.
4. From here, any doc-type whose (language, era, script) matches will start ranking this model against the older rounds — no further code changes.

### Per-corpus eval directory layout

```
~/eval_corpora/
    catmus-medieval/    PAGE XML + matching .jpg/.png  (or PNG + .gt.txt pairs)
    tridis/             same shape
    posner-em-latin/    held-out from training; the test bed for early modern
    cremma-charters/    same shape
```

Each subdirectory is treated as one corpus and gets its own CER row in the report. Pages inside can be PAGE XML, ALTO XML, or PNG+`.gt.txt` pairs — `transcriber-shell test-htr` autodetects.

### HTR input preprocessing

Off by default. When `TRANSCRIBER_SHELL_HTR_PREPROCESS_ENABLED=true`, each per-line crop is run through [`htr/preprocessing.py`](../src/transcriber_shell/htr/preprocessing.py) before the HTR backend sees it. The chain mirrors sibling `buzzcauldron/bib-ocr`'s tested settings for early modern print:

```bash
TRANSCRIBER_SHELL_HTR_PREPROCESS_ENABLED=true \
TRANSCRIBER_SHELL_HTR_PREPROCESS_INVERT=true \
TRANSCRIBER_SHELL_HTR_PREPROCESS_CONTRAST=2.0 \
TRANSCRIBER_SHELL_HTR_PREPROCESS_BINARISE=false \
transcriber-shell run --doc-type early_modern_latin --image page.jpg --prompt …
```

Individual knobs: `INVERT`, `CONTRAST` (1.0 = off), `SHARPEN`, `BINARISE`, `DESKEW_DEGREES`. Currently applied by the Tesseract backend; kraken integration is a follow-up.

## Document-type specs

Each profile in [`scripts/latin_ms/document_types/`](../scripts/latin_ms/document_types/) bundles an HTR model, segmentation model, prompt template, and primary/fallback LLM. The GUI's **Document type** dropdown reads from this directory.

| Doc-type | Language / era | Script | HTR model | Notes |
|----------|----------------|--------|-----------|-------|
| `medieval_latin_legal` | Latin / 1280–1420 | Anglicana cursiva | `htr_latin_updated_best.mlmodel` (round-4 fine-tune, CER 15.95% on val) | English plea rolls — King's Bench, Common Pleas, Eyre rolls; high abbreviation density. |
| `medieval_latin_ecclesiastical` | Latin / medieval | Gothic textura / cursiva | (see spec) | Charters, cartularies, registers. |
| `early_modern_latin` | Latin / 1500–1700 | Humanist roman/italic + carryover Gothic | `gm-htr-r2.mlmodel_best.mlmodel` (round-2 HF fine-tune) | Printed editions (astronomy, theology, law) and contemporaneous scribal hands. Watch long-s (ſ→f under Tesseract), æ/œ/⁊ ligatures, period abbreviations. Tesseract HTR (`lat+frk+eng`, PSM 7) usable as a second-opinion draft. |
| `early_modern_english` | English / 1500–1700 | Secretary hand | `transfer_learned_1k_lines.mlmodel` | Mixed Latin formulae in English documents; less abbreviation than medieval. |

To add a new profile, drop a `<name>.yaml` next to the existing ones (same fields: `name`, `language`, `era`, `script`, `llm`, `htr`, `segmentation`, `prompt`, `notes`) and add the name to the **Document type** combobox values in [`gui.py`](../src/transcriber_shell/gui.py).

## License and attribution

Respect the license and citation requirements of **ideasrule/latin_documents**. Keep **`TRANSCRIBER_SHELL_LINEATION_CREDIT_REPO_URL`** consistent with what you publish ([README](../README.md)).
