# Mask lineation plugin contract

`transcriber-shell` does not ship proprietary line-segmentation weights. The **mask** backend loads predictions through a small, stable interface so your **private** repository (for example an internal `latin_documents` checkout) can supply inference without publishing code or checkpoints in this repo.

For **training** on public page data, use **[ideasrule/latin_documents `data/`](https://github.com/ideasrule/latin_documents/tree/master/data)** (paired `.jpg` + PageXML `.xml`); see **[latin-documents-training-data.md](latin-documents-training-data.md)** and **`scripts/clone-latin-documents.sh`**.

## Callable signature

Set **`TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE`** to `module.path:function_name`.

The function must be importable and callable as:

```text
(image_path: Path, settings) -> numpy.ndarray
```

- **`image_path`:** Pre-cropped page image (same file the pipeline uses).
- **`settings`:** A `Settings` instance from `transcriber_shell.config` (duck-typing is fine). Useful fields:
  - **`mask_device`** — e.g. `cpu` or `cuda:0`
  - **`mask_weights_path`** — optional `Path` to a checkpoint (you read it inside your function)
  - **`mask_threshold`** — used later when converting masks to baselines (not applied inside `predict_masks`)

## Output tensor shape

Return **`pred`** with **`ndim == 3`**: shape **`(L, H, W)`** — one 2D mask per line (float or bool). A single line may use shape **`(H, W)`**; the pipeline will add an axis.

Spatial resolution can be smaller than the page; [`mask_lineation`](../src/transcriber_shell/mask_lineation.py) resizes masks to image dimensions before extracting baselines.

## Alternative: precomputed `.npy`

If inference runs outside Python or in another process, set **`TRANSCRIBER_SHELL_MASK_PRED_NPY_PATH`** to a path template with **`{stem}`** and/or **`{job_id}`** instead of using a callable.

## Installing a private package

Use SSH pip (or a private index) so secrets stay off the public internet:

```bash
pip install "git+ssh://git@github.com/yourorg/your-private-repo.git#subdirectory=packages/lineation"
```

Then:

```bash
export TRANSCRIBER_SHELL_LINEATION_BACKEND=mask
export TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=your_package.infer:predict_masks
```

## Example stub (public test double)

This repository includes **[`examples/latin_lineation_stub`](../examples/latin_lineation_stub/)** — a minimal installable package that returns a synthetic mask. Use it to verify env wiring and PageXML output before connecting a real model.

For **training** on [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents) `data/`, see **[`examples/latin_lineation_mvp`](../examples/latin_lineation_mvp/README.md)** (U-Net + `latin_lineation_mvp.infer:predict_masks`).

```bash
pip install -e "examples/latin_lineation_stub"
export TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=latin_lineation_stub.infer:predict_masks
```

## Weights and checkpoints

- Store **`.pt` / `.mlmodel` / checkpoints** in **private** storage (private GitHub Releases, S3, Hugging Face private, etc.).
- Put the resolved filesystem path in **`TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH`** and read **`settings.mask_weights_path`** inside your callable (or use your own env vars).
- Do **not** commit large weights to the **transcriber-shell** git repository.
- A **download or cache script** belongs in your **private** repo, not here; CI for this project does not install private lineation code.

## Attribution (`lineation_credit_repo_url`)

- For **published** PageXML or papers, you may set **`TRANSCRIBER_SHELL_LINEATION_CREDIT_REPO_URL`** to a **public** lab page, Zenodo DOI, or abstract repository.
- If the canonical GitHub repo must stay **private**, override the default URL with a short string such as `internal lineation model — contact authors` so metadata does not imply a public repository.

Generated mask PageXML includes a **Metadata/Comments** field with the credit string.

## Optional: align local baselines to Glyph Machina

If you save Glyph Machina PageXML for the same crop (same dimensions), set **`TRANSCRIBER_SHELL_MASK_REFERENCE_XML_PATH`** to a template such as `/data/gm/{stem}.xml` or `artifacts/{job_id}/glyph_machina.xml`. After mask lineation writes `lines.xml`, the pipeline **replaces** matched line baselines with the reference polylines, **removes** extra local lines, and **appends** missing reference lines. Tune **`TRANSCRIBER_SHELL_MASK_GM_CENTROID_MATCH_PX`** (default `120`) if centroids diverge. Baseline smoothing from masks uses **`TRANSCRIBER_SHELL_MASK_BASELINE_SMOOTH_WINDOW`** (default `5`, `0` to disable).

## Comparing to Glyph Machina (reference = perfect)

To score a **local** lines file against a **Glyph Machina** download for the same crop, use:

```bash
transcriber-shell compare-lines-xml -r glyph_machina-lines.xml -y artifacts/job/lines.xml
```

The command assumes **reference** baselines are ground truth: it reports **recall** (matched / reference lines), **precision** (matched / hypothesis lines), mean **Chamfer** distance on matched baselines (pixels), and indices of **missed** or **extra** lines. Tune **`--centroid-match-px`** if line centroids are far apart between exports.

## CI note

Public continuous integration for `transcriber-shell` uses **mocks** for lineation routes. Real GPU inference should run in **private** CI or **manual** jobs with credentials for your weights and packages.
