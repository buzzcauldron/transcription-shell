# Progress log

Append new entries at the **top** with **date** and short notes: what changed, which areas (pipeline, GUI, HTTP API, tests, docs).

### 2026-03-30 (GUI: Efficient mode visibility)
- **Area:** GUI
- **Changes:** **Efficient mode** checkbox moved to the **bottom bar** above **Transcribe** (was easy to miss mid-form). Run log prints `runMode=efficient|standard` for each run. README notes bottom-bar placement.
- **Blockers:** None.

### 2026-03-30 (GUI: persist keys to `.env`)
- **Area:** GUI, config UX, `env_persist`
- **Changes:** **Save keys to .env** merges `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, and `TRANSCRIBER_SHELL_OLLAMA_BASE_URL` into `.env` without dropping unrelated lines. Optional **Also save … after a successful run**. Form **hydrates** from existing `Settings`/`.env` on startup. README notes the behavior.
- **Blockers:** None.

### 2026-03-30 (Documentation stability — Axel-style split)
- **Area:** docs, README
- **Changes:** **architecture.md** holds prose only; **ARCHITECTURE.md** holds the **Mermaid** pipeline diagram (fixes duplicate files and a missing chart). **claude.md** router table clarifies which file to open. README **Layout** lists both docs. Session-style work is recorded here and in **decisions.md** instead of informal chat dumps.
- **Blockers:** None.

### 2026-03-30 (XML gate parity + execute bar)
- **Area:** config, CLI, GUI
- **Changes:** Optional **PAGE XSD** and **TextLine** requirement aligned across CLI (`--xsd`, `--no-require-text-line`, env `TRANSCRIBER_SHELL_LINES_XML_XSD` / `TRANSCRIBER_SHELL_XML_REQUIRE_TEXT_LINE`), **Settings**, and GUI (fields + browse). Primary run control moved to a **bottom bar** (**Transcribe**) so it stays visible; README wording matches.
- **Blockers:** None.

### 2026-03-30 (GUI models + efficient mode)
- **Area:** GUI, model_catalog
- **Changes:** Single **Model** dropdown lists **all** catalog IDs (budget + premium, sorted) via `merged_model_ids_for_selector`. **Efficient mode** checkbox sets `runMode: efficient` on the prompt copy before run. **Model** combobox and **Custom model id** are disabled when the active cloud provider has no API key in the form and none in `.env` (Ollama always enabled). Key fields `trace` updates enabled state.
- **Blockers:** None.

### 2026-03-30 (HCI follow-up)
- **Area:** Docs, GUI (HCI follow-up)
- **Changes:** README **Desktop GUI** subsection adds a short **recommended workflow** for academics/DH users and points to [claude.md](claude.md). GUI shows the same **recommended order** and **docs/claude.md** pointer under the subtitle (muted labels) to reduce scroll confusion without a heavy onboarding panel.
- **Blockers:** None.

## Template

```
### YYYY-MM-DD
- **Area:** …
- **Changes:** …
- **Blockers:** …
```

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
