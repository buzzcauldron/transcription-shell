# transcription-shell

**Python 3.11+** package **`transcriber-shell`** (`transcriber_shell`), built with **[Hatchling](https://hatch.pypa.io/)** from [`pyproject.toml`](pyproject.toml). Install from a **git checkout** using the **installer scripts** ([`scripts/install-local.sh`](scripts/install-local.sh) / [`scripts/install-local.ps1`](scripts/install-local.ps1)), **manual venv + pip**, or **Docker** — see [Installation](#installation) and [PACKAGING.md](PACKAGING.md).

Pipeline glue for **manuscript transcription** that combines:

1. **[Glyph Machina](https://glyphmachina.com/)** (browser automation) — upload a **pre-cropped** page image, **Identify Lines**, **Download Lines File** (PageXML-oriented lines export).
2. **XML checks** — well-formed XML + `TextLine` counts; optional **XSD** validation with `lxml` (`pip install 'transcriber-shell[xml-xsd]'`).
3. **LLM APIs** (Anthropic / OpenAI / optional Gemini) using prompts from the **[Academic Handwriting Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol)**.
4. **YAML validation** via vendored `validate_schema.py` from that protocol.

Glyph Machina outputs are used for **lineation only** — not as canonical diplomatic text. See [docs/glyph-machina-automation.md](docs/glyph-machina-automation.md).

## Installation

Pick one path; all assume a clone of this repository.

### Protocol submodule (required for LLM + YAML validation)

```bash
git submodule update --init vendor/transcription-protocol
```

Or clone with `git clone --recurse-submodules <repo-url>`. Without this, `validate-yaml` and transcription runs fail until `vendor/transcription-protocol/benchmark/` is present.

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

Copy [`.env.example`](.env.example) to `.env` and fill in values (local use only; never commit `.env`). The file is sectioned (comment blocks and optional defaults) similar to the **magic-elise-tool** diplomatic expander’s `.env.example`: API keys, defaults, paths, Glyph Machina, and optional HTTP API settings.

- **API keys:** set at least one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` (Gemini).
- **Default provider:** `TRANSCRIBER_SHELL_DEFAULT_PROVIDER` (`anthropic` | `openai` | `gemini` | `ollama`) when you omit `--provider` on the CLI.
- **Models:** per-provider vars (`TRANSCRIBER_SHELL_ANTHROPIC_MODEL`, …) or a single override `TRANSCRIBER_SHELL_MODEL` for the active provider. Precedence: **`--model` / `--provider` on the CLI** > `TRANSCRIBER_SHELL_MODEL` > per-provider defaults.
- **Optional HTTP API:** `TRANSCRIBER_SHELL_API_HOST` (default `127.0.0.1`), `TRANSCRIBER_SHELL_API_PORT` (default `8765`), optional `TRANSCRIBER_SHELL_API_KEY` (if set, require `Authorization: Bearer <key>` on `/v1/*`).

Install optional pieces:

```bash
pip install -e ".[api]"      # HTTP server (FastAPI + Uvicorn)
pip install -e ".[gemini]"   # Google Gemini
pip install -e ".[xml-xsd]"  # lxml for PAGE XSD validation
```

## Desktop GUI (simple, academic)

Primary way to run the pipeline interactively — **tkinter** only (no extra GUI packages). At the top, **Provider keys (LLM)** for Anthropic / OpenAI / Gemini: paste keys or leave empty and use `.env` (keys are **masked** by default; uncheck **Mask keys** to show). The optional **HTTP API** (`transcriber-shell serve`) is separate — use **HTTP API docs** in the GUI only after the server is running. Queue **multiple page images** via **Add files…** or **Add folder…** (non-recursive folder scan, same as CLI batch). With **Skip Glyph Machina** and **more than one image**, set **Lines XML dir** to a folder of `<stem>.xml` files (one per page). Then pick prompt, provider, and **Model** (all catalog IDs in one list; **Budget models only** narrows it). Optional **Efficient mode** forces protocol §2.9 single-pass behavior for that run. **Run transcription**. **Scan for Ollama / local tools** lists local models and PATH tools; provider **ollama** uses `ollama serve` (no cloud key).

```bash
transcriber-shell gui
# or
transcriber-shell-gui
```

Requires **Playwright Chromium** when not using skip-Glyph-Machina (same as CLI `run`). On Linux over SSH, use X11 forwarding or run with `--skip-gm` and a saved lines file.

**Recommended workflow (desktop):** (1) Add page images and choose prompt YAML/JSON. (2) Set provider and model (or custom id). (3) If not using Glyph Machina in the browser, enable **Skip Glyph Machina** and point to a lines XML file (one image) or folder of `<stem>.xml` files (batch). (4) **Run transcription**, then use **Open artifacts folder** (and the log for paths). Agent-oriented context lives in **[docs/claude.md](docs/claude.md)** (links to [architecture.md](docs/architecture.md), decisions, plan, progress).

## CLI

```bash
# PageXML / lines file sanity check
transcriber-shell validate-xml path/to/lines.xml --require-text-line

# Validate transcription YAML (needs submodule)
transcriber-shell validate-yaml path/to/out.yaml

# Full run: Glyph Machina → XML gate → LLM → schema validate
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --provider anthropic

# Optional: override model for this run
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --model claude-sonnet-4-20250514

# Skip browser; use an existing lines XML from another tool
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --skip-gm --lines-xml ./lines.xml

# Batch: every image in a folder or glob (artifacts per image stem)
transcriber-shell batch ./scans/ --prompt ./fixtures/prompt.example.yaml --batch-report ./batch-report.json

# Skip Glyph Machina in batch: one XML per image stem in a directory
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
- `pyproject.toml` — Python project metadata and extras (Hatchling build backend)
- `src/transcriber_shell/` — Python package (installs as `transcriber-shell` on PyPI); `gui.py` — desktop UI
- `vendor/transcription-protocol/` — git submodule (protocol specs + validators)
- `artifacts/<job_id>/` — Glyph Machina downloads and `transcription.yaml` outputs
- `Dockerfile`, `docker-compose.yml`, `docker-run.sh`, `build-docker.sh` — container install (see [README-DOCKER.md](README-DOCKER.md))
- `docker/entrypoint.sh` — editable install when `/workspace` is mounted
- `scripts/install-local.sh`, `scripts/install-local.ps1` — local venv installers (Unix / Windows)
- `VERSION` — Docker image tag (keep aligned with `pyproject.toml` version)

## License

MIT — see [LICENSE](LICENSE). The Academic Transcription Protocol remains under its own license in the submodule.
