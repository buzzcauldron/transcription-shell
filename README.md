# transcription-shell

Python package **`transcriber-shell`** (`transcriber_shell`) — pipeline glue for **manuscript transcription** that combines:

1. **[Glyph Machina](https://glyphmachina.com/)** (browser automation) — upload a **pre-cropped** page image, **Identify Lines**, **Download Lines File** (PageXML-oriented lines export).
2. **XML checks** — well-formed XML + `TextLine` counts; optional **XSD** validation with `lxml` (`pip install 'transcriber-shell[xml-xsd]'`).
3. **LLM APIs** (Anthropic / OpenAI / optional Gemini) using prompts from the **[Academic Handwriting Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol)**.
4. **YAML validation** via vendored `validate_schema.py` from that protocol.

Glyph Machina outputs are used for **lineation only** — not as canonical diplomatic text. See [docs/glyph-machina-automation.md](docs/glyph-machina-automation.md).

## Setup

**Option A — installer script** (venv + submodule + Playwright, same idea as visual-page-editor’s desktop installers):

```bash
cd transcription-shell
chmod +x scripts/install-local.sh   # once, if needed
./scripts/install-local.sh
source .venv/bin/activate
```

**Option B — manual**

```bash
cd transcription-shell
python -m venv .venv
source .venv/bin/activate
pip install -e ".[api,dev]"

# Playwright browser (required for Glyph Machina automation)
playwright install chromium
```

### Docker

Prebuilt image workflow (API or interactive shell), aligned with [visual-page-editor](https://github.com/buzzcauldron/visual-page-editor)’s `docker-run.sh` / Compose pattern: see **[README-DOCKER.md](README-DOCKER.md)** (`./docker-run.sh`, `./docker-run.sh shell`, `docker compose`).

### Protocol submodule

```bash
git submodule update --init vendor/transcription-protocol
```

Or add when cloning:

```bash
git clone --recurse-submodules <repo-url>
```

If the submodule is missing, LLM + `validate-yaml` will fail until `benchmark/validate_schema.py` and `prompt_builder.py` are available under `vendor/transcription-protocol/benchmark/`.

## Configuration

Copy [`.env.example`](.env.example) to `.env` and fill in values (local use only; never commit `.env`). The file is sectioned (comment blocks and optional defaults) similar to the **magic-elise-tool** diplomatic expander’s `.env.example`: API keys, defaults, paths, Glyph Machina, and optional HTTP API settings.

- **API keys:** set at least one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` (Gemini).
- **Default provider:** `TRANSCRIBER_SHELL_DEFAULT_PROVIDER` (`anthropic` | `openai` | `gemini`) when you omit `--provider` on the CLI.
- **Models:** per-provider vars (`TRANSCRIBER_SHELL_ANTHROPIC_MODEL`, …) or a single override `TRANSCRIBER_SHELL_MODEL` for the active provider. Precedence: **`--model` / `--provider` on the CLI** > `TRANSCRIBER_SHELL_MODEL` > per-provider defaults.
- **Optional HTTP API:** `TRANSCRIBER_SHELL_API_HOST` (default `127.0.0.1`), `TRANSCRIBER_SHELL_API_PORT` (default `8765`), optional `TRANSCRIBER_SHELL_API_KEY` (if set, require `Authorization: Bearer <key>` on `/v1/*`).

Install optional pieces:

```bash
pip install -e ".[api]"      # HTTP server (FastAPI + Uvicorn)
pip install -e ".[gemini]"   # Google Gemini
pip install -e ".[xml-xsd]"  # lxml for PAGE XSD validation
```

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

- `GET /health` — liveness.
- `POST /v1/transcribe` — `multipart/form-data`: `files` (one or more images), `prompt` (YAML/JSON string of the same CONFIGURATION object as the CLI), optional `provider`, `model`, `inline_yaml` (embed `transcription_yaml` text in the JSON response). **Not supported:** `skip_gm` on this route (use the CLI with `--lines-xml` / `--lines-xml-dir` if you need offline line files).

Bind defaults to **localhost**; add an API key via `.env` for local multi-user setups. Do not expose without a reverse proxy and auth in production.

## Layout

- `src/transcriber_shell/` — Python package (installs as `transcriber-shell` on PyPI)
- `vendor/transcription-protocol/` — git submodule (protocol specs + validators)
- `artifacts/<job_id>/` — Glyph Machina downloads and `transcription.yaml` outputs
- `Dockerfile`, `docker-compose.yml`, `docker-run.sh`, `build-docker.sh` — container install (see [README-DOCKER.md](README-DOCKER.md))
- `docker/entrypoint.sh` — editable install when `/workspace` is mounted
- `scripts/install-local.sh` — local venv installer
- `VERSION` — Docker image tag (keep aligned with `pyproject.toml` version)

## License

MIT — see [LICENSE](LICENSE). The Academic Transcription Protocol remains under its own license in the submodule.
