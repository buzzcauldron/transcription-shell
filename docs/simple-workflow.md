# Simple workflow

The program does **one thing in order**:

1. **Lineation attempt** — Try to obtain a **lines XML** for the pre-cropped page image (where each text line is on the page).  
   **Default:** [Glyph Machina](https://glyphmachina.com/) in a browser (Playwright).  
   **Alternatives:** [mask](mask-lineation-plugin.md) or **Kraken** (`TRANSCRIBER_SHELL_LINEATION_BACKEND`), or **skip** automated lineation and supply a file you already have (`--skip-gm` / GUI “Skip automated lineation”).  
   On **failure** (timeout, backend error), the run **stops** unless you enabled **[continue-on-lineation-failure](#when-automated-lineation-fails)**—then the pipeline continues with **image + prompt only** (no lines XML).

2. **Check XML** — When a lines file exists, basic sanity checks on that file (optional skip / XSD per settings). Nothing to validate when step 1 continued without lines XML.

3. **Transcribe** — Send the image + prompt to your LLM (Anthropic, OpenAI, Gemini, or Ollama) using the [Academic Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol) prompt config.

4. **Check YAML** — Validate the model’s transcription YAML (`<image_stem>_transcription.yaml`) against the protocol schema.

Output goes under **`artifacts/<job_id>/`** (e.g. `page_transcription.yaml` for `page.jpg`, lines XML copy).

Older versions of this tool wrote a fixed filename `transcription.yaml` instead; **`--skip-successful` and the GUI skip option only recognize `<image_stem>_transcription.yaml`.** Rename old files if you rely on skip.

**Log lines** such as `lines_xml=`, `transcription_yaml=`, and `text_line_count=` are explained in **[log-lines-xml-text-line-count.md](log-lines-xml-text-line-count.md)** (including why `text_line_count` can differ between runs).

### When automated lineation fails

By default, a **Glyph Machina timeout**, **mask/Kraken error**, or other lineation failure **stops the run** so you do not lose line-aligned output silently.

If you prefer to **continue to the LLM with only the page image and protocol prompt** (no lines XML), enable **`TRANSCRIBER_SHELL_CONTINUE_ON_LINEATION_FAILURE`** or **`--continue-on-lineation-failure`** (CLI) / the matching GUI checkbox. The pipeline logs a **warning**; `lines_xml` is absent and `text_line_count` is **0**. Segment **`lineRange`** alignment in the YAML may be weaker than with PageXML—supply manual lines XML or retry lineation when quality matters.

---

## What you need for the default path

- Repo clone + **protocol submodule** (`vendor/transcription-protocol`) — see [README](../README.md).
- **`.env`** or GUI: at least one LLM API key (or Ollama running locally).
- **Playwright Chromium** for Glyph Machina: `python -m playwright install chromium` (see [local-setup.md](local-setup.md)).
- A **prompt** file (YAML/JSON) and one or more **page images**.

**Commands:**

```bash
transcriber-shell gui
# or
transcriber-shell run --job-id myjob --image ./page.png --prompt ./fixtures/prompt.example.yaml --provider anthropic
```

---

## What is optional (ignore until you need it)

| Topic | Why it exists |
|--------|----------------|
| **Mask / Kraken lineation** | You have your own line detector or no browser |
| **Train a local mask model** | [`scripts/train_local_mask_lineation.py`](../scripts/train_local_mask_lineation.py) wraps [`examples/latin_lineation_mvp`](../examples/latin_lineation_mvp/README.md) (`latin_documents` data → `predict_masks`); see [latin-documents-training-data.md](latin-documents-training-data.md) |
| **`transcriber-shell serve`** | HTTP API instead of CLI/GUI |
| **Batch / globs** | Many pages at once |
| **XSD / compare-lines-xml / validate-*** | QA and tooling around the same pipeline |
| **Docker, extras `[kraken]`, `[api]`** | Deployment or specific backends |

Full install and env vars: **[local-setup.md](local-setup.md)**. Packaging: **[PACKAGING.md](../PACKAGING.md)**.

If a **batch** failed partway (Glyph Machina vs LLM), see **[recovery-batch.md](recovery-batch.md)** and run **`python scripts/check_anthropic_key.py`** to verify Anthropic credentials.

To **delete old outputs and rerun from the GUI** (artifacts folder, skip-successful checkbox, Transcribe): **[gui-cleanup-and-rerun.md](gui-cleanup-and-rerun.md)**.
