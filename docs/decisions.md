# Decisions (append only)

Record non-obvious choices here: **date**, **decision**, **rationale**, **impact**. Optional: **Author**.

## Template

```
### YYYY-MM-DD — short title
- **Decision:** …
- **Rationale:** …
- **Impact:** …
- **Author:** (optional)
```

### 2026-03-30 — GUI primary actions in a bottom bar
- **Decision:** Place **Transcribe**, **Open artifacts folder**, and **HTTP API docs** in a frame packed with `side=BOTTOM` before the main column; status line under those buttons.
- **Rationale:** A large `ScrolledText` log with `expand=True` sat below the former action row, so on typical window heights the run controls could sit entirely above the visible area (no scroll on the outer window).
- **Impact:** Primary actions stay on screen; copy refers to “Transcribe (bottom bar).”

### 2026-03-30 — XML gate defaults in Settings (CLI / GUI parity)
- **Decision:** Add `lines_xml_xsd` and `xml_require_text_line` to `Settings`; resolve CLI `run`/`batch` XSD path with `_resolve_xsd_path` (explicit `--xsd` overrides env); `require_text_line` respects `--no-require-text-line` then `xml_require_text_line`. GUI initializes fields from `Settings` and passes resolved paths into `run_pipeline` / `run_batch`.
- **Rationale:** The GUI had hardcoded `xsd_path=None` and `require_text_line=True`, losing parity with optional CLI behavior.
- **Impact:** Optional XSD and relaxed TextLine rules behave consistently; `.env.example` documents env keys.

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
