# latin_lineation_mvp — train line masks on `latin_documents` data

Small **U-Net** that predicts one channel per handwritten line (rasterized from PageXML baselines), packaged as **`predict_masks`** for [transcriber-shell](../../docs/mask-lineation-plugin.md).

## Install

```bash
cd /path/to/transcription-shell
pip install -e "examples/latin_lineation_mvp"
```

Requires **PyTorch** (CPU or CUDA).

## Train

Clone [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents) (`data/` with paired `.jpg` + `.xml`), then:

```bash
latin-lineation-train --data-dir /path/to/latin_documents/data --epochs 30 --out ./line_mask_unet.pt --device cuda
```

Writes **`line_mask_unet.pt`** and **`line_mask_unet.json`** (metadata: `max_lines`, `mask_h`, `mask_w`).

**Long runs:** the trainer uses **cosine LR** over all epochs and saves the **best val-loss** checkpoint (not necessarily the last epoch—watch for overfitting after ~10–20 epochs on small corpora). Example: `--epochs 100 --device cuda:0 --lr 1e-3`.

**Resume after interrupt / reboot:** each completed epoch writes **`<out_stem>.train.pt`** next to `--out` (e.g. `line_mask_unet.train.pt` beside `line_mask_unet.pt`) with model, optimizer, scheduler, RNG, and epoch. Continue with:

```bash
latin-lineation-train --data-dir /path/to/latin_documents/data --epochs 100 --out ./line_mask_unet.pt --resume auto
```

Use the **same** `--seed`, `--val-ratio`, `--mask-h`, `--mask-w`, `--line-width`, `--max-lines`, and `--data-dir` as the original run (the script checks `meta`). **`--epochs` may be larger** than the previous run (training continues until that total); if it differs, the LR schedule is rebuilt and fast-forwarded to the last completed epoch.

**Boot helper:** from the repo root, set `LATIN_DOCUMENTS_DATA` and optionally `LINE_MASK_OUT`, `LINE_MASK_EPOCHS`, `LINE_MASK_DEVICE`, then run [`scripts/resume-lineation-training.sh`](../../scripts/resume-lineation-training.sh).

Example **systemd user** unit (`~/.config/systemd/user/lineation-train.service`):

```ini
[Unit]
Description=Resume latin line mask training
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/transcription-shell
Environment=LATIN_DOCUMENTS_DATA=%h/data/latin_documents/data
Environment=LINE_MASK_OUT=%h/transcription-shell/artifacts/training/line_mask_unet.pt
ExecStart=%h/transcription-shell/scripts/resume-lineation-training.sh
Restart=on-failure

[Install]
WantedBy=default.target
```

Then: `systemctl --user daemon-reload` and `systemctl --user enable --now lineation-train.service` (only if you want training to start on every login/boot).

**Inference tuning** (especially on pages unlike the training set): adjust shell/env **`TRANSCRIBER_SHELL_MASK_THRESHOLD`**, **`MASK_CHANNEL_MIN_MASS`**, **`MASK_CHANNEL_MIN_PEAK`**, **`MASK_MAX_OUTPUT_LINES`** (see [`.env.example`](../../.env.example)).

## Inference (transcriber-shell)

```bash
export TRANSCRIBER_SHELL_LINEATION_BACKEND=mask
export TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=latin_lineation_mvp.infer:predict_masks
export TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH=/absolute/path/to/line_mask_unet.pt
# Optional post-processing (tune after training):
# export TRANSCRIBER_SHELL_MASK_THRESHOLD=0.5
# export TRANSCRIBER_SHELL_MASK_BASELINE_SMOOTH_WINDOW=5
```

## Benchmark vs Glyph Machina

After you have a **reference** PageXML from Glyph Machina and **local** `lines.xml` from the pipeline:

```bash
python scripts/benchmark_gm_parity.py --reference gm.xml --hypothesis artifacts/job/lines.xml
```

Or: `transcriber-shell compare-lines-xml -r gm.xml -y local.xml`

## Alternative: Kraken BLLA

If you prefer **VGSL / Kraken** (as in upstream `run_segmenter.py`) instead of mask tensors, use **`TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken`** and **`TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH`** — no `predict_masks` required.
