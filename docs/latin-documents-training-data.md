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
