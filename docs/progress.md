# Progress log

Append new entries at the **top** with **date** and short notes: what changed, which areas (pipeline, GUI, HTTP API, tests, docs).

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
