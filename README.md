# transcriber-shell

Pipeline glue for **manuscript transcription** that combines:

1. **[Glyph Machina](https://glyphmachina.com/)** (browser automation) — upload a **pre-cropped** page image, **Identify Lines**, **Download Lines File** (PageXML-oriented lines export).
2. **XML checks** — well-formed XML + `TextLine` counts; optional **XSD** validation with `lxml` (`pip install 'transcriber-shell[xml-xsd]'`).
3. **LLM APIs** (Anthropic / OpenAI / optional Gemini) using prompts from the **[Academic Handwriting Transcription Protocol](https://github.com/buzzcauldron/transcription-protocol)**.
4. **YAML validation** via vendored `validate_schema.py` from that protocol.

Glyph Machina outputs are used for **lineation only** — not as canonical diplomatic text. See [docs/glyph-machina-automation.md](docs/glyph-machina-automation.md).

## Setup

```bash
cd transcriber-shell
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Playwright browser (required for Glyph Machina automation)
playwright install chromium
```

### Protocol submodule

```bash
git submodule update --init vendor/transcription-protocol
```

Or add when cloning:

```bash
git clone --recurse-submodules <repo-url>
```

If the submodule is missing, LLM + `validate-yaml` will fail until `benchmark/validate_schema.py` and `prompt_builder.py` are available under `vendor/transcription-protocol/benchmark/`.

## Environment

Copy `.env.example` to `.env` and set at least one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY` (for Gemini).

## CLI

```bash
# PageXML / lines file sanity check
transcriber-shell validate-xml path/to/lines.xml --require-text-line

# Validate transcription YAML (needs submodule)
transcriber-shell validate-yaml path/to/out.yaml

# Full run: Glyph Machina → XML gate → LLM → schema validate
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --provider anthropic

# Skip browser; use an existing lines XML from another tool
transcriber-shell run --job-id demo1 --image ./crop.jpg --prompt ./fixtures/prompt.example.yaml --skip-gm --lines-xml ./lines.xml
```

## Layout

- `src/transcriber_shell/` — package code
- `vendor/transcription-protocol/` — git submodule (protocol specs + validators)
- `artifacts/<job_id>/` — Glyph Machina downloads and `transcription.yaml` outputs

## License

MIT — see [LICENSE](LICENSE). The Academic Transcription Protocol remains under its own license in the submodule.
