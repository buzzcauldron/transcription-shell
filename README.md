# transcription-shell

**Python 3.11+** package **`transcriber-shell`** (`transcriber_shell`), built with **[Hatchling](https://hatch.pypa.io/)** from [`pyproject.toml`](pyproject.toml). Install from a **git checkout** using the **installer scripts** ([`scripts/install-local.sh`](scripts/install-local.sh) / [`scripts/install-local.ps1`](scripts/install-local.ps1)), **manual venv + pip**, or **Docker** — see [Installation](#installation) and [PACKAGING.md](PACKAGING.md).

Pipeline glue for **manuscript transcription** that combines:

1. **Lineation** (choose via `TRANSCRIBER_SHELL_LINEATION_BACKEND` or `--lineation-backend`):
   - **`mask` (default)** — per-line masks → PageXML baselines (`TextLine` / `Baseline`). Supply **`TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE`** (`pkg.mod:function`) and/or **`TRANSCRIBER_SHELL_MASK_PRED_NPY_PATH`** (path with `{stem}` / `{job_id}`). Lineation methods and training context align with **[ideasrule/latin_documents](https://github.com/ideasrule/latin_documents)** (credit also in generated XML metadata).
   - **`kraken`** — local **[Kraken](https://github.com/mittagessen/kraken)** BLLA + PageXML (`pip install 'transcriber-shell[kraken]'`, set **`TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH`**).
   - **`glyph_machina`** — **[Glyph Machina](https://glyphmachina.com/)** in the browser (Playwright). See [docs/glyph-machina-automation.md](docs/glyph-machina-automation.md).
2. **XML checks** — well-formed XML + `TextLine` counts; optional **XSD** validation with `lxml` (`pip install 'transcriber-shell[xml-xsd]'`).
3. **LLM APIs** (Anthropic / OpenAI / optional Gemini) using prompts from the **[Academic Handwriting Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol)**.
4. **YAML validation** via vendored `validate_schema.py` from that protocol.

Downstream **baseline → rectified line image** tooling from the same research line lives in [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents); line exports aim for compatible `Baseline@points` where possible. Glyph Machina outputs are used for **lineation only** when that backend is selected — not as canonical diplomatic text.

To **train** a mask model on that project’s public page data (`data/` — paired `.jpg` + PageXML), use the optional **[examples/latin_lineation_mvp](examples/latin_lineation_mvp/README.md)** package (`latin-lineation-train`, then `latin_lineation_mvp.infer:predict_masks`), or see **[docs/latin-documents-training-data.md](docs/latin-documents-training-data.md)** and **`scripts/clone-latin-documents.sh`**. **`scripts/benchmark_gm_parity.py`** scores local `lines.xml` against a Glyph Machina reference.

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

playwright install chromium   # required for Glyph Machina automation
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

Primary way to run the pipeline interactively — **tkinter** only (no extra GUI packages). At the top, **Provider keys (LLM)** for Anthropic / OpenAI / Gemini: paste keys or leave empty and use `.env` (keys are **masked** by default; uncheck **Mask keys** to show). The optional **HTTP API** (`transcriber-shell serve`) is separate — use **HTTP API docs** in the GUI only after the server is running. Choose **Lineation backend** when not skipping lineation. Queue **multiple page images** via **Add files…** or **Add folder…** (non-recursive folder scan, same as CLI batch). With **skip automated lineation** and **more than one image**, set **Lines XML dir** to a folder of `<stem>.xml` files (one per page). Then pick prompt, provider, and **Model** (all catalog IDs in one list; **Budget models only** narrows it). Optional **Efficient mode** forces protocol §2.9 single-pass behavior for that run. **Run transcription**. **Scan for Ollama / local tools** lists local models and PATH tools; provider **ollama** uses `ollama serve` (no cloud key).

```bash
transcriber-shell gui
# or
transcriber-shell-gui
```

Requires **Playwright Chromium** only when **lineation backend** is **glyph_machina** and you are not using `--skip-gm`. On Linux over SSH, use X11 forwarding or run with `--skip-gm` and a saved lines file.

**Recommended workflow (desktop):** (1) Add page images and choose prompt YAML/JSON. (2) Set provider and model (or custom id). (3) Configure mask / Kraken / Glyph Machina in `.env`, or enable **skip automated lineation** and point to a lines XML file (one image) or folder of `<stem>.xml` files (batch). (4) **Run transcription**, then use **Open artifacts folder** (and the log for paths). Agent-oriented context lives in **[docs/claude.md](docs/claude.md)** (links to [architecture.md](docs/architecture.md), decisions, plan, progress).

## CLI

```bash
# PageXML / lines file sanity check
transcriber-shell validate-xml path/to/lines.xml --require-text-line

# Compare local lineation XML to Glyph Machina (reference treated as perfect ground truth)
transcriber-shell compare-lines-xml -r gm-lines.xml -y local-lines.xml
# transcriber-shell compare-lines-xml -r ref.xml -y hyp.xml --centroid-match-px 80 --json

# Validate transcription YAML (needs submodule)
transcriber-shell validate-yaml path/to/out.yaml

# Full run: lineation → XML gate → LLM → schema validate (default backend: mask; configure .env)
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --provider anthropic

# Use Kraken or Glyph Machina instead of mask
# transcriber-shell run ... --lineation-backend kraken
# transcriber-shell run ... --lineation-backend glyph_machina

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
- `pyproject.toml` — Python project metadata and extras (Hatchling build backend)
- `src/transcriber_shell/` — Python package (installs as `transcriber-shell` on PyPI); `gui.py` — desktop UI
- `vendor/transcription-protocol/` — git submodule (protocol specs + validators)
- `artifacts/<job_id>/` — lines XML and `transcription.yaml` outputs
- `Dockerfile`, `docker-compose.yml`, `docker-run.sh`, `build-docker.sh` — container install (see [README-DOCKER.md](README-DOCKER.md))
- `docker/entrypoint.sh` — editable install when `/workspace` is mounted
- `scripts/install-local.sh`, `scripts/install-local.ps1` — local venv installers (Unix / Windows)
- `VERSION` — Docker image tag (keep aligned with `pyproject.toml` version)

## License

MIT — see [LICENSE](LICENSE). The Academic Transcription Protocol remains under its own license in the submodule.
