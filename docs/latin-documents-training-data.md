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

2. **Train** with **`latin_lineation_mvp`** (see its README) or your own code on `data/*.jpg` + `data/*.xml`. Outputs must match [mask-lineation-plugin.md](mask-lineation-plugin.md): **`(L, H, W)`** float masks.

3. **Point transcriber-shell** at **`latin_lineation_mvp.infer:predict_masks`** (or your module) and the **`.pt`** checkpoint path.

4. **Optional:** compare to Glyph Machina using `transcriber-shell compare-lines-xml` or **`scripts/benchmark_gm_parity.py`** ([README](../README.md)).

## License and attribution

Respect the license and citation requirements of **ideasrule/latin_documents**. Keep **`TRANSCRIBER_SHELL_LINEATION_CREDIT_REPO_URL`** consistent with what you publish ([README](../README.md)).
