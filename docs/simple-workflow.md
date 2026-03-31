# Simple workflow

The program does **one thing in order**:

1. **Lines** — Turn a pre-cropped page image into a lines XML file (where the text lines are on the page).  
   **Default:** [Glyph Machina](https://glyphmachina.com/) in a browser (Playwright).  
   **Alternative:** skip this step and point at a lines XML you already have (`--skip-gm` / GUI “Skip automated lineation”).

2. **Check XML** — Basic sanity checks on that lines file.

3. **Transcribe** — Send the image + prompt to your LLM (Anthropic, OpenAI, Gemini, or Ollama) using the [Academic Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol) prompt config.

4. **Check YAML** — Validate the model’s `transcription.yaml` against the protocol schema.

Output goes under **`artifacts/<job_id>/`** (e.g. `transcription.yaml`, lines XML copy).

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
| **`transcriber-shell serve`** | HTTP API instead of CLI/GUI |
| **Batch / globs** | Many pages at once |
| **XSD / compare-lines-xml / validate-*** | QA and tooling around the same pipeline |
| **Docker, extras `[kraken]`, `[api]`** | Deployment or specific backends |

Full install and env vars: **[local-setup.md](local-setup.md)**. Packaging: **[PACKAGING.md](../PACKAGING.md)**.
