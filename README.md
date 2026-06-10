# transcription-shell

<!-- transcriber-shell-sync:pyproject.version -->
**Version 0.1.0** · Python 3.11+ — canonical metadata in [`pyproject.toml`](pyproject.toml). After a pull or version bump, run `python scripts/sync_repo_docs.py`.
<!-- transcriber-shell-sync:end:pyproject.version -->

**Python 3.11+** package **`transcriber-shell`** (`transcriber_shell`), built with **[Hatchling](https://hatch.pypa.io/)** from [`pyproject.toml`](pyproject.toml). It installs from a **git checkout** — see [Quick start](#quick-start) for the fast path, or [Installation](#installation) / [PACKAGING.md](PACKAGING.md) for installer scripts, manual venv, and Docker.

**Simple mental model:** pre-cropped image → **lines XML** (default: Glyph Machina in the browser) → **LLM** with a protocol prompt → **`<image_stem>_transcription.yaml`** (e.g. `page_transcription.yaml` for `page.jpg`). Optional pieces (mask/Kraken, HTTP API, batch, extra validators) are documented in **[docs/simple-workflow.md](docs/simple-workflow.md)**; details below are for reference.

## Quick start

From zero to a first transcription:

```bash
# 1. Clone with the protocol submodule (required for LLM + YAML validation)
git clone --recurse-submodules https://github.com/buzzcauldron/transcription-shell.git
cd transcription-shell

# 2. Install: creates .venv, installs deps, Playwright Chromium, inits the submodule
./scripts/install-local.sh          # Windows: .\scripts\install-local.ps1
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1

# 3. Add at least one LLM API key
cp .env.example .env                # then edit: ANTHROPIC_API_KEY=...  (or OPENAI_API_KEY / GOOGLE_API_KEY)
```

Then transcribe one page, either way:

```bash
# Easiest — desktop GUI (drag images in, pick prompt + model, click Transcribe)
transcriber-shell gui

# Or one page from the CLI (default lineation runs Glyph Machina in a browser)
transcriber-shell run --job-id demo1 --image ./crop.jpg \
  --prompt ./fixtures/prompt.example.yaml --provider anthropic
# → output: artifacts/demo1/crop_transcription.yaml
```

No browser? Add `--skip-gm --lines-xml ./lines.xml` to supply line boxes from another tool. More backends, batch mode, and Docker are in [Installation](#installation) and the [CLI](#cli) section below.

## How it works

Four stages, each swappable:

1. **Lineation** — detect the text lines on the page and write a PageXML `lines.xml`. Default backend is **[Glyph Machina](https://glyphmachina.com/)** (runs in a browser via Playwright); switch to a local **Kraken** model or a custom **mask** model with `--lineation-backend` (details in [Configuration](#configuration)).
2. **XML check** — confirm the lines file is well-formed and has the expected `TextLine` count before spending an LLM call.
3. **LLM transcription** — send the image plus a protocol prompt to Anthropic / OpenAI / Gemini, following the **[Academic Handwriting Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol)**.
4. **YAML validation** — check the model's output against the protocol schema (vendored `validate_schema.py`).

Output lands at `artifacts/<job_id>/<image_stem>_transcription.yaml`. Optional **HTR backends** (Kraken and/or Glyph Machina) can run alongside the LLM for comparison — enable them in [Configuration](#configuration). Trained segmentation / HTR models and how to reproduce them: **[docs/MODELS.md](docs/MODELS.md)**.

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

The primary way to run the pipeline interactively (**tkinter** + **tkinterdnd2** for drag-and-drop). Launch it with:

```bash
transcriber-shell gui
# or
transcriber-shell-gui
```

**Typical workflow:**

1. **Add page images** — **Add files…**, **Add folder…**, or drag files/folders onto the **Page images** list (non-recursive folder scan, same as CLI batch).
2. **Set provider keys** — paste Anthropic / OpenAI / Gemini keys at the top, or leave empty to use `.env`. Keys are **masked** by default (uncheck **Mask keys** to show). **Save keys to .env** persists them; opt into **save after a successful run** to skip the extra click.
3. **Choose lineation** — pick a **Lineation backend**, or enable **skip automated lineation** and point to a lines XML file (one image) / **Lines XML dir** of `<stem>.xml` files (batch).
4. **Pick prompt, provider, and Model** — all catalog IDs appear in one list; **Budget models only** narrows it. Optional **Efficient mode** (next to **Transcribe**) sets `runMode: efficient` for that run (protocol §2.9, single-pass).
5. **Transcribe** (bottom bar), then **Open artifacts folder** for outputs. **Save log…** is at the right of the bottom bar.

**Notes:**

- Requires **Playwright Chromium** only when the lineation backend is **glyph_machina** and you are not using `--skip-gm`. On Linux over SSH, use X11 forwarding or run with `--skip-gm` and a saved lines file.
- **Scan for Ollama / local tools** lists local models and PATH tools; provider **ollama** uses `ollama serve` (no cloud key).
- The optional **HTTP API** (`transcriber-shell serve`) is separate — the GUI's **HTTP API docs** button only works once that server is running.
- Agent-oriented context lives in **[docs/claude.md](docs/claude.md)** (links to [architecture.md](docs/architecture.md), decisions, plan, progress).

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

## Prompt Configs

Ready-made prompt YAML files live in [`scripts/latin_ms/`](scripts/latin_ms/). Each document type has a **diplomatic** variant (abbreviations preserved as Unicode combining chars) and an **expansion** variant (abbreviations written out as full words, evaluable against expanded PAGE XML ground truth):

| File | Mode | Corpus |
|---|---|---|
| [`prompt_charter.yaml`](scripts/latin_ms/prompt_charter.yaml) | diplomatic | Continental charters (Monasterium.net, 8th–15th c.) |
| [`prompt_charter_expanded.yaml`](scripts/latin_ms/prompt_charter_expanded.yaml) | **expansion** | Same corpus — use for GT-scored evaluation |
| [`prompt_anglicana_legal_diplomatic.yaml`](scripts/latin_ms/prompt_anglicana_legal_diplomatic.yaml) | diplomatic | English royal court plea rolls (KB27, CP40, AALT) |
| [`prompt_anglicana_legal.yaml`](scripts/latin_ms/prompt_anglicana_legal.yaml) | **expansion** | Same corpus — use for GT-scored evaluation |

**Firewall rule:** diplomatic outputs (`preserveOriginalAbbreviations: true`) must never be scored against expanded PAGE XML ground truth — the CER will be artificially inflated by 20–40 points. The evaluator in `benchmark/evaluate.py` enforces this and will abort with an error if the modes are mixed. Use `--force` only for acknowledged ad-hoc comparisons.

## TEI Export

Convert `*_transcription.yaml` artifacts to TEI P5 XML:

```bash
# Single file
transcriber-shell yaml-to-tei artifacts/page_001/page_001_transcription.yaml -o page_001_tei.xml

# Batch: all YAMLs in an artifacts directory
transcriber-shell yaml-to-tei --dir artifacts/ --out-dir tei/
```

Each segment becomes a `<p rend="{position}">` element in `<body>`. When the segment carries a `lineRange`, physical manuscript lines are emitted as `<lb n="N"/>` milestones — one per newline-delimited line in the transcript text:

```xml
<p rend="body">
  <lb n="3"/>prima linea
  <lb n="4"/>secunda linea
  <lb n="5"/>tertia linea
</p>
```

Special positions: `interlinear` → `<add place="above">`; `table_row` / `table_header` → `<table><row><cell>` (pipe-delimited columns). `confidence` maps to `@cert`. The logic lives in [src/transcriber_shell/xml_tools/tei.py](src/transcriber_shell/xml_tools/tei.py); position→TEI mapping details are in [vendor/transcription-protocol/README.md](vendor/transcription-protocol/README.md#tei-export).

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

## Blind-test benchmarks

Scored against protocol ground truth (additions + omissions vs. GT character count). Run date: **2026-06-10**. All cases use Gemini 2.5 Pro as the LLM; "shell" configs add a Kraken HTR draft in correct-mode. See [`scripts/stress_shell_run.py`](scripts/stress_shell_run.py) and [`artifacts/blind-test-training/plan.md`](artifacts/blind-test-training/plan.md) for methodology.

| Case | Manuscript | Era | Script | Best shell (HTR model) | Image-only | Δ | Status |
|------|-----------|-----|--------|----------------------|-----------|---|--------|
| BM-KB27 | King's Bench plea roll | ~1340 | Anglicana legal | 26.9% (r2) | 31.7% | −4.8pt | Anglicana retraining in progress |
| BM-MED-001 | Walters W.25 psalter | ~1200 | Gothic Latin | **88.0% (r5)** | 86.0% | **+2.0pt** | Shell beats image-only |
| BM-001 | Lincoln letter | 1837 | English copperplate | 94.5% (r5) | 95.1% | −0.6pt | Solved (schema violation on position field) |
| BM-MOD-DEED | 1865 deed | 1865 | Modern hand | **97.4% (computus)** | 98.7%† | −1.3pt | Solved; shell fixes schema failures |
| BM-MOD-LOVEJOY | Lovejoy letter | 1864 | English copperplate | **82.4% (computus)** | — *(YAML parse fail)* | — | Shell fixes parse errors |

† Image-only reaches 98.7% but fails schema validation (`position` enum); shell result is lower accuracy but schema-valid.

> **Schema note:** Most runs fail the protocol validation gate due to `position` enum drift — the LLM outputs values like `top`, `marginalia`, `address` that aren't in the protocol's controlled vocabulary. The shell normalizes these for Latin cases. A fix pass for English cases is pending.

## Research & training extras

For contributors and metric work — not needed for normal transcription:

- **Downstream line-image tooling** — baseline → rectified line image tooling from the same research line lives in [ideasrule/latin_documents](https://github.com/ideasrule/latin_documents); line exports aim for compatible `Baseline@points`. Glyph Machina outputs are used for **lineation only** when that backend is selected — not as canonical diplomatic text.
- **Train a mask model** — on that project's public page data (`data/` — paired `.jpg` + PageXML), use the optional **[examples/latin_lineation_mvp](examples/latin_lineation_mvp/README.md)** package (`latin-lineation-train`, then `latin_lineation_mvp.infer:predict_masks`), or see **[docs/latin-documents-training-data.md](docs/latin-documents-training-data.md)** and **`scripts/clone-latin-documents.sh`**. **`scripts/benchmark_gm_parity.py`** scores local `lines.xml` against a Glyph Machina reference.
- **Human ground truth** (PAGE XML comparable to GM for metrics) — **[docs/ground-truth-human-annotation.md](docs/ground-truth-human-annotation.md)**, calibration workflow **[docs/ground-truth-calibration.md](docs/ground-truth-calibration.md)**, folder layout **[ground_truth/README.md](ground_truth/README.md)**. Validate with **`transcriber-shell validate-gt-pagexml page.xml page.png`**.
- **`text_line_count` in logs** — what it means and why it differs across jobs: **[docs/log-lines-xml-text-line-count.md](docs/log-lines-xml-text-line-count.md)**.

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

## Credits

**HTR model — medieval documentary sources (Latin/French)**

> Pinche, Ariane; Camps, Jean-Baptiste; Ing, Lionel (2023). *HTR model for medieval documentary sources*. Zenodo. <https://doi.org/10.5281/zenodo.7547438>. Licence: CC BY 4.0.

Used as the `kraken-htr` backend (`TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH`). Set the path to `HTR_medieval_documentary_best.mlmodel` downloaded from the Zenodo record above.

**Glyph Machina (HTR pipeline)**

> *glyph_machina_public*. ideasrule. <https://github.com/ideasrule/glyph_machina_public>.

Used as the optional `gm-htr` backend (`TRANSCRIBER_SHELL_GM_HTR_REPO_PATH`). Clone that repository and point the env var at the checkout root.

**Glyph Machina training dataset**

> mzzhang2014. *glyph_machina* [dataset]. Hugging Face. <https://huggingface.co/datasets/mzzhang2014/glyph_machina>.

**Kraken OCR engine**

> Kiessling, Benjamin. *Kraken*. <https://github.com/mittagessen/kraken>.

Used for BLLA segmentation (lineation backend `kraken`) and HTR inference.

**Glyph Machina website / browser automation**

> *Glyph Machina*. <https://glyphmachina.com/>. Used for the default `glyph_machina` lineation backend.

**ideasrule/latin_documents**

> <https://github.com/ideasrule/latin_documents>. Lineation methods, training data, and baseline conventions referenced by the `mask` backend.

**Academic Handwriting Transcription Protocol**

> <https://github.com/buzzcauldron/transcription-protocol>. Prompt format and YAML schema validated by this pipeline.

## License

**CC BY 4.0** (Creative Commons Attribution 4.0 International) — see [LICENSE](LICENSE). The Academic Transcription Protocol remains under its own license in the submodule.
