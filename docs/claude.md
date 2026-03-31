# Session context (router)

**transcriber-shell** — manuscript transcription pipeline: lineation (mask / Kraken / Glyph Machina), PageXML checks, LLM transcription (Anthropic / OpenAI / Gemini / Ollama), optional HTTP API and desktop GUI.

The **GUI** (`transcriber-shell gui`) repeats a short **recommended workflow** under the title and points here for deeper context.

Use this file as the **entry point** when starting a new agent session. Jump to the doc that matches your task:

| Doc | When to open |
|-----|----------------|
| [local-setup.md](local-setup.md) | Clone, venv, `.env`, lineation backends, smoke tests, troubleshooting |
| [architecture.md](architecture.md) | System shape, modules, data flow, how pieces connect |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Mermaid diagram of the pipeline (canonical diagram) |
| [claude_openai_reference.md](claude_openai_reference.md) | OpenAI models, env vars, vision chat path in this repo |
| [decisions.md](decisions.md) | Append-only record of decisions (date, why, impact) |
| [plan.md](plan.md) | Prioritized checklist of planned work |
| [progress.md](progress.md) | What changed recently, by date and area |

In **Cursor**, you can reference files with `@docs/architecture.md` (or paths under `docs/`) so the model loads the right context without pasting long chats.

**Convention:** Update `decisions.md` when you lock in a non-obvious choice; update `plan.md` when priorities shift; append to `progress.md` when you finish a meaningful chunk of work.

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
