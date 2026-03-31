# latin-lineation-stub

**Example only.** Implements the `transcriber-shell` mask plugin contract so you can test wiring without a private model.

Real lineation belongs in your private repo (e.g. `latin_documents`): copy this layout, replace `predict_masks` with your torch inference, and load weights from `settings.mask_weights_path` or your own env vars.

## Install (editable)

From the repository root:

```bash
pip install -e "examples/latin_lineation_stub"
```

## Configure transcriber-shell

```bash
export TRANSCRIBER_SHELL_LINEATION_BACKEND=mask
export TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=latin_lineation_stub.infer:predict_masks
```

Optional:

```bash
export TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH=/path/to/weights.pt   # stub ignores unless you extend it
```

## Private package install (for your real repo)

```bash
pip install "git+ssh://git@github.com/yourorg/your-private-lineation.git"
```

Then set `TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE` to your module’s `predict_masks`.
