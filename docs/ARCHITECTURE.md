# Architecture (living overview)

**transcriber-shell** orchestrates:

1. **Lineation** — Browser automation against [Glyph Machina](https://glyphmachina.com/) (`transcriber_shell.glyph_machina`) to produce a lines XML for a pre-cropped page image, unless `--skip-gm` / GUI “Skip Glyph Machina” supplies existing XML.
2. **XML gate** — Well-formed XML, `TextLine` checks, optional XSD (`transcriber_shell.xml_tools`).
3. **LLM** — `prompt_builder` + provider adapters (`transcriber_shell.llm`) produce protocol-shaped YAML; models listed in `llm/model_catalog.py`.
4. **Validation** — Vendored `validate_schema` from `vendor/transcription-protocol/benchmark/` (submodule required).
5. **Outputs** — `artifacts/<job_id>/` (lines XML, transcription YAML, etc.).

**Surfaces:**

- **CLI** — `transcriber-shell run`, `batch`, `validate-*`, etc.
- **GUI** — `transcriber-shell gui` (`transcriber_shell.gui`).
- **HTTP API (optional)** — FastAPI under `transcriber_shell.api` (`pip install '.[api]'`), `serve` command.

**Protocol code** lives in the submodule `vendor/transcription-protocol/`; runtime adds `benchmark/` to `sys.path` for `prompt_builder` and validators.

For the **diagram** of the pipeline, see **[ARCHITECTURE.md](ARCHITECTURE.md)** (single source of truth for the mermaid chart).

Other deep dives: [glyph-machina-automation.md](glyph-machina-automation.md).

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
