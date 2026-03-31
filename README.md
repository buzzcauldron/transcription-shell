# transcription-shell

<!-- transcriber-shell-sync:pyproject.version -->
**Version 0.1.0** · Python 3.11+ — canonical metadata in [`pyproject.toml`](pyproject.toml). After a pull or version bump, run `python scripts/sync_repo_docs.py`.
<!-- transcriber-shell-sync:end:pyproject.version -->

**Python 3.11+** package **`transcriber-shell`** (`transcriber_shell`), built with **[Hatchling](https://hatch.pypa.io/)** from [`pyproject.toml`](pyproject.toml). Install from a **git checkout** using the **installer scripts** ([`scripts/install-local.sh`](scripts/install-local.sh) / [`scripts/install-local.ps1`](scripts/install-local.ps1)), **manual venv + pip**, or **Docker** — see [Installation](#installation) and [PACKAGING.md](PACKAGING.md).

**Simple mental model:** pre-cropped image → **lines XML** (default: Glyph Machina in the browser) → **LLM** with a protocol prompt → **`<image_stem>_transcription.yaml`** (e.g. `page_transcription.yaml` for `page.jpg`). Start with **`transcriber-shell gui`** or **`transcriber-shell run --job-id … --image … --prompt …`**. Optional pieces (mask/Kraken, HTTP API, batch, extra validators) are documented in **[docs/simple-workflow.md](docs/simple-workflow.md)**; details below are for reference.

Pipeline glue for **manuscript transcription** that combines:

1. **Lineation** (choose via `TRANSCRIBER_SHELL_LINEATION_BACKEND` or `--lineation-backend`):
   - **`glyph_machina` (default)** — **[Glyph Machina](https://glyphmachina.com/)** in the browser (Playwright). See [docs/glyph-machina-automation.md](docs/glyph-machina-automation.md).
   - **`mask`** — per-line masks → PageXML baselines (`TextLine` / `Baseline`). Supply **`TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE`** (`pkg.mod:function`) and/or **`TRANSCRIBER_SHELL_MASK_PRED_NPY_PATH`** (path with `{stem}` / `{job_id}`). Lineation methods and training context align with **[ideasrule/latin_documents](https://github.com/ideasrule/latin_documents)** (credit also in generated XML metadata).
   - **`kraken`** — local **[Kraken](https://github.com/mittagessen/kraken)** BLLA + PageXML (`pip install 'transcriber-shell[kraken]'`, set **`TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH`**).
2. **XML checks** — well-formed XML + `TextLine` counts; optional **XSD** validation with `lxml` (`pip install 'transcriber-shell[xml-xsd]'`). What **`text_line_count`** in CLI/GUI logs means (and why it differs across jobs): **[docs/log-lines-xml-text-line-count.md](docs/log-lines-xml-text-line-count.md)**.
3. **LLM APIs** (Anthropic / OpenAI / optional Gemini) using prompts from the **[Academic Handwriting Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol)**.
4. **YAML validation** via vendored `validate_schema.py` from that protocol.

Downstream **baseline → rectified line image** tooling from the same research line lives in [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents); line exports aim for compatible `Baseline@points` where possible. Glyph Machina outputs are used for **lineation only** when that backend is selected — not as canonical diplomatic text.

To **train** a mask model on that project’s public page data (`data/` — paired `.jpg` + PageXML), use the optional **[examples/latin_lineation_mvp](examples/latin_lineation_mvp/README.md)** package (`latin-lineation-train`, then `latin_lineation_mvp.infer:predict_masks`), or see **[docs/latin-documents-training-data.md](docs/latin-documents-training-data.md)** and **`scripts/clone-latin-documents.sh`**. **`scripts/benchmark_gm_parity.py`** scores local `lines.xml` against a Glyph Machina reference.

**Human ground truth** (PAGE XML comparable to GM for metrics): **[docs/ground-truth-human-annotation.md](docs/ground-truth-human-annotation.md)**, calibration workflow **[docs/ground-truth-calibration.md](docs/ground-truth-calibration.md)**, folder layout **[ground_truth/README.md](ground_truth/README.md)**. Validate with **`transcriber-shell validate-gt-pagexml page.xml page.png`**.

## Installation

Pick one path; all assume a clone of this repository.

### Protocol submodule (required for LLM + YAML validation)

```bash
git submodule update --init vendor/transcription-protocol
```

Or clone with `git clone --recurse-submodules <repo-url>`. Without this, `validate-yaml` and transcription runs fail until `vendor/transcription-protocol/benchmark/` is present.

**Step-by-step local install (venv, `.env`, lineation backends, troubleshooting):** **[docs/local-setup.md](docs/local-setup.md)**.

### Option A — installer script (recommended)

**Linux / macOS** — venv, editable install, Playwright Chromium, submodule init:

```bash
cd transcription-shell
chmod +x scripts/install-local.sh   # once, if needed
./scripts/install-local.sh
source .venv/bin/activate
```

**Windows (PowerShell)**:

```powershell
cd transcription-shell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # once, if scripts are blocked
.\scripts\install-local.ps1
.\.venv\Scripts\Activate.ps1
```

### Option B — manual pip / venv

```bash
cd transcription-shell
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e ".[api,dev,gemini,xml-xsd]"

python -m playwright install chromium   # required for default Glyph Machina lineation; use venv’s Python
```

### Option C — Docker

Container image with Python, Playwright, and deps; repo mounted at `/workspace`. Full details: **[README-DOCKER.md](README-DOCKER.md)**.

```bash
git submodule update --init vendor/transcription-protocol   # required before docker build
./docker-run.sh              # API → http://127.0.0.1:8765
./docker-run.sh shell        # interactive bash, /workspace = repo
# or: docker compose --env-file .env.docker up --build api
```

## Configuration

Copy [`.env.example`](.env.example) to `.env` and fill in values (local use only; never commit `.env`). The file is sectioned (comment blocks and optional defaults) similar to the **magic-elise-tool** diplomatic expander’s `.env.example`: API keys, defaults, paths, lineation (mask / Kraken / Glyph Machina), and optional HTTP API settings. For a full local checklist (submodules, extras, smoke tests, compare-lines-xml), see **[docs/local-setup.md](docs/local-setup.md)**.

- **API keys:** set at least one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` (Gemini).
- **Default provider:** `TRANSCRIBER_SHELL_DEFAULT_PROVIDER` (`anthropic` | `openai` | `gemini` | `ollama`) when you omit `--provider` on the CLI.
- **Models:** per-provider vars (`TRANSCRIBER_SHELL_ANTHROPIC_MODEL`, …) or a single override `TRANSCRIBER_SHELL_MODEL` for the active provider. Precedence: **`--model` / `--provider` on the CLI** > `TRANSCRIBER_SHELL_MODEL` > per-provider defaults.
- **Optional HTTP API:** `TRANSCRIBER_SHELL_API_HOST` (default `127.0.0.1`), `TRANSCRIBER_SHELL_API_PORT` (default `8765`), optional `TRANSCRIBER_SHELL_API_KEY` (if set, require `Authorization: Bearer <key>` on `/v1/*`).
- **LLM HTTP proxy (optional):** `TRANSCRIBER_SHELL_LLM_USE_PROXY` and `TRANSCRIBER_SHELL_LLM_HTTP_PROXY` for corporate proxies; see `.env.example` and [docs/glyph-machina-automation.md](docs/glyph-machina-automation.md) for **persistent Glyph Machina browser profile** (`TRANSCRIBER_SHELL_GM_PERSISTENT_PROFILE`).

Install optional pieces:

```bash
pip install -e ".[api]"      # HTTP server (FastAPI + Uvicorn)
pip install -e ".[gemini]"   # Google Gemini
pip install -e ".[xml-xsd]"  # lxml for PAGE XSD validation
pip install -e ".[mask]"     # optional: scipy / opencv / torch helpers for custom mask inference
pip install -e ".[kraken]"   # optional: Kraken BLLA lineation
```

**Mask backend + private models:** the pipeline loads inference via **`TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE`** (see **[docs/mask-lineation-plugin.md](docs/mask-lineation-plugin.md)**). Optional **`TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH`** is passed to your callable as **`settings.mask_weights_path`**. For a test double without proprietary weights: `pip install -e "examples/latin_lineation_stub"` and set the callable to `latin_lineation_stub.infer:predict_masks`.

## Desktop GUI (simple, academic)

Primary way to run the pipeline interactively — **tkinter** plus **tkinterdnd2** (declared dependency) for drag-and-drop onto the **Page images** list. At the top, **Provider keys (LLM)** for Anthropic / OpenAI / Gemini: paste keys or leave empty and use `.env` (keys are **masked** by default; uncheck **Mask keys** to show). **Save keys to .env** writes the current fields into `.env` in the working directory; you can also opt in to **save after a successful run** so keys persist without an extra click. The optional **HTTP API** (`transcriber-shell serve`) is separate — use **HTTP API docs** in the GUI only after the server is running. Choose **Lineation backend** when not skipping lineation. Queue **multiple page images** via **Add files…**, **Add folder…**, or **drag files/folders onto the list** (non-recursive folder scan, same as CLI batch). With **skip automated lineation** and **more than one image**, set **Lines XML dir** to a folder of `<stem>.xml` files (one per page). Then pick prompt, provider, and **Model** (all catalog IDs in one list; **Budget models only** narrows it). Optional **Efficient mode** (bottom bar, next to **Transcribe**) sets `runMode: efficient` for that run (protocol §2.9 single-pass). **Transcribe** (bottom bar); **Save log…** is on the **right** of that bar. **Scan for Ollama / local tools** lists local models and PATH tools; provider **ollama** uses `ollama serve` (no cloud key).

```bash
transcriber-shell gui
# or
transcriber-shell-gui
```

Requires **Playwright Chromium** only when **lineation backend** is **glyph_machina** and you are not using `--skip-gm`. On Linux over SSH, use X11 forwarding or run with `--skip-gm` and a saved lines file.

**Recommended workflow (desktop):** (1) Add page images and choose prompt YAML/JSON. (2) Set provider and model (or custom id). (3) Configure mask / Kraken / Glyph Machina in `.env`, or enable **skip automated lineation** and point to a lines XML file (one image) or folder of `<stem>.xml` files (batch). (4) **Transcribe** (bottom bar), then use **Open artifacts folder** (and the log for paths). Agent-oriented context lives in **[docs/claude.md](docs/claude.md)** (links to [architecture.md](docs/architecture.md), decisions, plan, progress).

## CLI

```bash
# PageXML / lines file sanity check
transcriber-shell validate-xml path/to/lines.xml --require-text-line

# Compare local lineation XML to Glyph Machina (reference treated as perfect ground truth)
transcriber-shell compare-lines-xml -r gm-lines.xml -y local-lines.xml
# transcriber-shell compare-lines-xml -r ref.xml -y hyp.xml --centroid-match-px 80 --json

# Validate transcription YAML (needs submodule)
transcriber-shell validate-yaml path/to/out.yaml

# Full run: lineation → XML gate → LLM → schema validate (default backend: glyph_machina; configure .env)
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --provider anthropic

# Use mask or Kraken instead of Glyph Machina
# transcriber-shell run ... --lineation-backend mask
# transcriber-shell run ... --lineation-backend kraken

# Optional: override model for this run
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --model claude-sonnet-4-20250514

# Skip browser; use an existing lines XML from another tool
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --skip-gm --lines-xml ./lines.xml

# Batch: every image in a folder or glob (artifacts per image stem)
transcriber-shell batch ./scans/ --prompt ./fixtures/prompt.example.yaml --batch-report ./batch-report.json

# Skip lineation in batch: one XML per image stem in a directory
transcriber-shell batch ./scans/ --prompt ./fixtures/prompt.example.yaml --skip-gm --lines-xml-dir ./lines/
```

## HTTP API (optional)

Requires `pip install -e ".[api]"`.

```bash
transcriber-shell serve
# or
uvicorn transcriber_shell.api.app:app --host 127.0.0.1 --port 8765
```

- `GET /` — redirects to **`/docs`** (so the server root is never an empty 404). Prefer **`transcriber-shell gui`** for normal use.
- `GET /health` — liveness.
- `POST /v1/transcribe` — `multipart/form-data`: `files` (one or more images), `prompt` (YAML/JSON string of the same CONFIGURATION object as the CLI), optional `provider`, `model`, `inline_yaml` (embed `transcription_yaml` text in the JSON response). **Not supported:** `skip_gm` on this route (use the CLI with `--lines-xml` / `--lines-xml-dir` if you need offline line files).

Bind defaults to **localhost**; add an API key via `.env` for local multi-user setups. Do not expose without a reverse proxy and auth in production.

**Upload size:** The app enforces a **per-image** maximum (see `docs/red_team_review.md`). A reverse proxy should still set a **total** body limit (for example nginx `client_max_body_size`) because **many files × per-file cap** can add up to a very large multipart body.

## Development

```bash
pip install -e ".[api,dev,xml-xsd]"
pytest
```

Continuous integration runs the same suite on Python 3.11 and 3.12 (see `.github/workflows/ci.yml`).

## Layout

- `docs/claude.md` — session / agent context router (links to architecture, decisions, plan, progress)
- `docs/local-setup.md` — clone, venv, `.env`, lineation backends, smoke tests, troubleshooting
- `docs/mask-lineation-plugin.md` — mask backend plugin contract and private-repo install notes
- `examples/latin_lineation_stub/` — example installable plugin (synthetic masks) for testing wiring
- `docs/architecture.md` — architecture (Mermaid pipeline diagram + prose)
- `docs/red_team_review.md` — threat notes, API limits, residual risks
- `pyproject.toml` — Python project metadata and extras (Hatchling build backend)
- `src/transcriber_shell/` — Python package (installs as `transcriber-shell` on PyPI); `gui.py` — desktop UI
- `vendor/transcription-protocol/` — git submodule (protocol specs + validators)
- `artifacts/<job_id>/` — lines XML and `<image_stem>_transcription.yaml` outputs
- `Dockerfile`, `docker-compose.yml`, `docker-run.sh`, `build-docker.sh` — container install (see [README-DOCKER.md](README-DOCKER.md))
- `docker/entrypoint.sh` — editable install when `/workspace` is mounted
- `scripts/install-local.sh`, `scripts/install-local.ps1` — local venv installers (Unix / Windows)
- `VERSION` — Docker image tag; keep in sync with `pyproject.toml` via `python scripts/sync_repo_docs.py` (updates markdown too) or `python scripts/check_version.py --sync` (VERSION only)

## License

**CC BY 4.0** (Creative Commons Attribution 4.0 International) — see [LICENSE](LICENSE). The Academic Transcription Protocol remains under its own license in the submodule.
