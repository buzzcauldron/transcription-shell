# Recovering from a mixed batch failure

Use this when some jobs **failed at Glyph Machina** (timeouts) and others **failed at the LLM** (e.g. bad API key) after lineation already produced lines XML.

If Glyph Machina **keeps timing out** and you accept transcription **without** lines XML for those pages, see **`--continue-on-lineation-failure`** / **`TRANSCRIBER_SHELL_CONTINUE_ON_LINEATION_FAILURE`** in **[simple-workflow.md](simple-workflow.md)** (tradeoffs: weaker line alignment).

## 1. Fix LLM authentication first

Until the provider accepts your key, every image that reaches the transcription step will fail.

- Set **`ANTHROPIC_API_KEY`** or **`TRANSCRIBER_SHELL_ANTHROPIC_API_KEY`** in `.env`, or paste the key in the GUI and use **Save keys to .env**.
- Verify from the repo root:

```bash
python scripts/check_anthropic_key.py
```

Exit code **0** means the key works for a minimal API call. **1** means missing key or authentication failure.

To use another provider instead, set **`TRANSCRIBER_SHELL_DEFAULT_PROVIDER`** (or pass `--provider` on `run` / `batch`) and the matching key.

## 2. Re-transcribe images that already have lines XML (skip Glyph Machina)

Do **not** re-run browser lineation for pages that already succeeded; reuse the lines XML under **`artifacts/<job_id>/`**.

### Naming for `--lines-xml-dir`

Batch with **`--skip-gm`** expects either:

- **`--lines-xml`** — single image only; path to that page’s XML, or  
- **`--lines-xml-dir`** — one **`.xml` per image stem**: for `page.jpg` the file must be **`page.xml`** in that directory (same stem as the image).

Glyph Machina often saves the download with a **different filename** (e.g. a UUID). **Copy or symlink** the XML you need into a folder, named **`{stem}.xml`** where `stem` is the image filename without extension (e.g. `cursive deed.jpg` → `cursive deed.xml`).

Example (adjust paths):

```bash
mkdir -p ./lines-xml-for-batch
cp "artifacts/cursive_deed/31161ef4-8973-4518-b134-7d1b169a617c.xml" "./lines-xml-for-batch/cursive deed.xml"
cp "artifacts/hardest/4b323321-d0e5-41f1-ae3a-f2992745b6ed.xml" "./lines-xml-for-batch/hardest.xml"
# ... one file per image stem you want to re-run
```

Then run batch over the **same images** with skip-GM:

```bash
transcriber-shell batch "/path/to/images/folder" \
  --prompt fixtures/prompt.example.yaml \
  --provider anthropic \
  --skip-gm \
  --lines-xml-dir ./lines-xml-for-batch
```

Use a **directory or glob** that lists only the images you want to process (or process all and rely on **`--skip-successful`** if valid `*_transcription.yaml` already exist).

### Alternative: `run` per image

For full control, call **`transcriber-shell run`** once per page with the exact XML path:

```bash
transcriber-shell run --job-id cursive_deed \
  --image "/path/to/cursive deed.jpg" \
  --prompt fixtures/prompt.example.yaml \
  --provider anthropic \
  --skip-gm \
  --lines-xml "/path/to/artifacts/cursive_deed/your-lines.xml"
```

## 3. Retry lineation only for pages that failed at Glyph Machina

For images with **no** usable lines XML yet:

- Prefer a **stable network**; corporate VPNs sometimes cause `[Errno 60] Operation timed out`.
- Try a **visible** browser once: **`TRANSCRIBER_SHELL_GM_HEADLESS=false`** (see [glyph-machina-automation.md](glyph-machina-automation.md)).
- If timeouts continue, raise **`TRANSCRIBER_SHELL_GM_IDENTIFY_TIMEOUT_MS`** and **`TRANSCRIBER_SHELL_GM_POST_IDENTIFY_WAIT_MS`** in `.env` (defaults and descriptions: [`pyproject.toml`](../pyproject.toml) / [`config.py`](../src/transcriber_shell/config.py)).

Then run **`run`** or **`batch`** **without** `--skip-gm` for those images only (narrow `--path` or glob).

## 4. Habit: keep lines XML for re-runs

After a successful Glyph Machina step, **archive** `*.xml` next to the scan or in a folder of **`{stem}.xml`** files. For model or prompt experiments, use **`--skip-gm`** so you are not blocked by the site or Playwright on every attempt.

## See also

- [simple-workflow.md](simple-workflow.md) — pipeline order  
- [glyph-machina-automation.md](glyph-machina-automation.md) — GM env vars and profiles  
- [claude_anthropic_reference.md](claude_anthropic_reference.md) — Anthropic troubleshooting  
