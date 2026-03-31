# Session context (router)

<!-- transcriber-shell-sync:pyproject.version -->
**Version 0.1.0** · Python 3.11+ — canonical metadata in [`pyproject.toml`](../pyproject.toml). After a pull or version bump, run `python scripts/sync_repo_docs.py`.
<!-- transcriber-shell-sync:end:pyproject.version -->

**transcriber-shell** — manuscript transcription pipeline: lineation (mask / Kraken / Glyph Machina), PageXML checks, LLM transcription (Anthropic / OpenAI / Gemini / Ollama), optional HTTP API and desktop GUI.

The **GUI** (`transcriber-shell gui`) repeats a short **recommended workflow** under the title and points here for deeper context.

Use this file as the **entry point** when starting a new agent session. Jump to the doc that matches your task:

| Doc | When to open |
|-----|----------------|
| [local-setup.md](local-setup.md) | Clone, venv, `.env`, lineation backends, smoke tests, troubleshooting |
| [recovery-batch.md](recovery-batch.md) | After a failed batch: fix keys, `--skip-gm` + lines XML, retry GM only for failed pages |
| [gui-cleanup-and-rerun.md](gui-cleanup-and-rerun.md) | Delete `artifacts/` outputs in Finder, adjust skip-successful, rerun Transcribe in the GUI |
| [architecture.md](architecture.md) | Pipeline **Mermaid** diagram + prose: stages, surfaces (CLI / GUI / API), links to code |
| [claude_openai_reference.md](claude_openai_reference.md) | OpenAI models, env vars, vision chat path in this repo |
| [claude_anthropic_reference.md](claude_anthropic_reference.md) | Anthropic (Claude) env vars, streaming adapter, timeouts/retries, common failures |
| [decisions.md](decisions.md) | Append-only record of decisions (date, why, impact) |
| [plan.md](plan.md) | Prioritized checklist of planned work |
| [progress.md](progress.md) | What changed recently, by date and area |

In **Cursor**, you can reference files with `@docs/architecture.md` (or paths under `docs/`) so the model loads the right context without pasting long chats.

**Convention:** Update `decisions.md` when you lock in a non-obvious choice; update `plan.md` when priorities shift; append to `progress.md` when you finish a meaningful chunk of work.

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
