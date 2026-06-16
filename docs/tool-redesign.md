# Transcriber-shell tool redesign

A proposal for restructuring the transcription pipeline as composable modules,
each toggleable independently, with auto-routing driven by language detection.

## Implementation status (as of 2026-05)

This document is the **target architecture**. The table below tracks what **ships today** in `transcriber-shell` versus what remains proposed.

| Area | Shipped today | This doc |
|------|---------------|----------|
| Orchestrator | Single [`run_pipeline()`](../src/transcriber_shell/pipeline/run.py) | Composable `PipelineModule` + `ctx` |
| Job config | Prompt YAML/JSON + env + CLI flags (`--prompt`, `--skip-gm`, …). **`transcriber-shell run --config pipeline.yaml` is not implemented.** | One `pipeline.yaml` per project |
| GUI | Collapsible sections (tkinter) | Five pipeline rows + per-row ⚙ |
| Kraken BLLA `threshold` / `min_length` | [`Settings`](../src/transcriber_shell/config.py) defaults **`0.10` / `100`**; passed into `blla.segment` when supported ([`kraken_lineation.py`](../src/transcriber_shell/kraken_lineation.py), [`glyph_machina/local.py`](../src/transcriber_shell/glyph_machina/local.py)) | Phase 2 — **met for local Kraken seg**; GM **website** fallback lineation may still differ |
| `normalizationMode` | GUI **Diplomatic** checkbox, CLI **`--diplomatic`**, API form **`diplomatic`** (default false), and [`set_normalization_mode_for_diplomatic()`](../src/transcriber_shell/pipeline/run.py) align defaults with **normalized** (LLM `normalizedLayer`). See [simple-workflow.md](simple-workflow.md). | Future `output.normalization` in `pipeline.yaml` must keep the **same default** unless the user opts in to diplomatic-only |
| HTR drafts | [`PipelineResult.htr_results`](../src/transcriber_shell/models/job.py) + optional hint into the LLM | Each module surfaces drafts in the UI |
| `llm-correct` modes | Full protocol transcribe; **`xml_only`** skips LLM; HTR scheduling via **`htr_combination`** / `htr_parallel` in settings | Distinct **`off` / `correct` / `full`** prompts |
| Language | From **prompt fields** and settings, not a standalone module | **`language-detect`** module |

**Migration phases (status):**

1. **Phase 1** — Not started (no shared `PipelineModule` / `Context` type in-tree yet).
2. **Phase 2** — **Largely done** for Kraken BLLA when `threshold` / `min_length` exist on `blla.segment`. Open: vendor GM Kraken fork vs upstream if you need **exact** GM segmenter parity beyond those kwargs.
3. **Phase 3** — Not started (short **correct** prompt).
4. **Phase 4** — Not started (row-per-module GUI).
5. **Phase 5** — Not started (optional VLM language detect).

**Design notes for when Phases 1 and 3 land:**

- **`ctx` mutability** — Prefer explicit per-step results or documented ordering invariants (e.g. HTR-before-LLM only for certain `htr_combination` values) so partial runs and retries stay debuggable.
- **`language-detect`** — Keep **prompt-cfg** the default; any VLM router should stay **opt-in** to avoid an extra LLM call on every page.

## Why redesign

The current pipeline is a fixed chain — lineation → HTR (optional combo) → LLM
— with most knobs hidden across collapsible GUI sections. The Glyph Machina
upstream shows a cleaner shape: four discrete scripts (segmenter,
line-image-generator, htr, optional gemini), each independently runnable. We
should adopt that shape internally so every stage is testable, swappable, and
optional.

## Reference: GM upstream pipeline

From `glyph_machina_public/README.md`, the end-to-end is four commands:

```
python run_segmenter.py seg.mlmodel image.JPG image.xml
python run_line_image_generator.py image.xml   # writes per-line PNGs next to xml
python run_htr.py image.xml                    # in-place TextEquiv injection
python run_gemini.py image.xml corrected.xml   # optional LLM correction
```

Each step reads/writes PageXML in-place — clean handoff, no coupling. The
README also notes that the segmenter's defaults (`threshold=0.17`,
`min_length=5`) are wrong for AALT-style charters; `threshold=0.10` and
`min_length=100` work materially better.

## Proposed module shape

Five modules, each implementing a tiny interface:

```python
class PipelineModule(Protocol):
    name: str                      # "lineation", "htr-kraken", "llm-correct", ...
    def applies(self, ctx) -> bool # cheap precondition check
    def run(self, ctx) -> ctx      # mutate-and-return; ctx carries paths + state
```

The `ctx` carries: `image_path`, `lines_xml_path | None`,
`htr_drafts: dict[str, HtrResult]`, `language: str | None`,
`transcription_text: str | None`, `errors`, `warnings`, `timings`.

**The five modules:**

1. **`language-detect`** — runs first, sets `ctx.language`. Two backends:
   - `prompt-cfg` (current keyword approach, cheap)
   - `vlm-quick` (small Haiku call: "what language/script is this?")
   Auto-routes downstream model selection.

2. **`lineation`** — produces `lines_xml_path`. Backends:
   - `kraken` — local BLLA. Must accept `threshold` and `min_length` (the GM
     fork exposes them; vendor that fork or add the same args ourselves).
   - `glyph-machina` — browser fallback for hard pages.
   - `mask` — for manuscripts with existing line masks.

3. **`htr`** — fills `ctx.htr_drafts`. Each backend is its own sub-module the
   user can toggle:
   - `kraken-htr` (son-of-gm-r*)
   - `gm-htr` (best_HTR.net subprocess)
   - Future: `trocr`, `pylaia`, etc.
   The language detected by module 1 chooses which models apply; an "all" mode
   runs every applicable backend in parallel.

4. **`llm-correct`** — takes the HTR drafts, optionally produces a
   protocol-compliant transcription. Modes:
   - `off` — write best HTR draft as final output (current `htr_only`).
   - `correct` — short prompt, treat HTR as primary, just fix errors.
   - `full` — current behavior, full protocol YAML.
   The split between `correct` and `full` matters: when Kraken hits ~95%
   accuracy, `correct` is 5-10× cheaper because the prompt is "fix these
   spots" rather than "transcribe this image."

5. **`output`** — writes results in the requested format(s):
   - Raw text (`.txt`)
   - PageXML with embedded TextEquiv (GM-compatible)
   - Protocol YAML (current)
   - Diplomatic vs. normalized (toggle, drives `normalizationMode`)

## Config flow

One `pipeline.yaml` per project (or per job):

```yaml
modules:
  - name: language-detect
    backend: prompt-cfg
  - name: lineation
    backend: kraken
    threshold: 0.10
    min_length: 100
  - name: htr
    backends: [kraken-htr, gm-htr]   # parallel
  - name: llm-correct
    mode: correct
    model: claude-haiku-4-5-20251001
  - name: output
    formats: [yaml, txt, pagexml]
    # Default matches GUI (Diplomatic off) / CLI without --diplomatic / API without diplomatic=true.
    normalization: normalized   # use "diplomatic" for main text only (no normalizedLayer)
```

CLI (future): `transcriber-shell run --config pipeline.yaml image.jpg`.
Today: `transcriber-shell run --job-id … --image … --prompt …` plus optional `--diplomatic`; see [simple-workflow.md](simple-workflow.md).
GUI: each module is a row with `[✓] enabled`, a backend dropdown, and a
"configure" button that opens just that module's settings. No collapsibles for
the common path.

## GUI shape

```
┌─ Transcriber shell ──────────────────────────────────┐
│  Images: [...drop or browse...]                       │
│  Prompt: [...]                                        │
│                                                       │
│  Pipeline                                             │
│  [✓] Language detect    backend: prompt-cfg     [⚙]  │
│  [✓] Lineation          backend: kraken         [⚙]  │
│  [✓] HTR                kraken + gm (parallel)  [⚙]  │
│  [✓] LLM correct        mode: correct (haiku)   [⚙]  │
│  [✓] Output             yaml + txt, normalized  [⚙]  │
│                                                       │
│  [ Transcribe ]   elapsed: —   tokens: —             │
└───────────────────────────────────────────────────────┘
```

Provider keys, browser settings, etc. live behind a single ⚙ on each module
that needs them. The default screen is five rows. The user sees the whole
pipeline at a glance.

## Migration

Don't rewrite — wrap. Keep `run_pipeline()` as-is; build a thin module layer
on top of the existing functions:

1. **Phase 1**: define `PipelineModule` protocol and `Context` dataclass.
   Wrap each existing stage (`fetch_lines_xml_*`, `run_htr_*`, `run_transcribe`)
   as a module. No behavior changes. Backed by tests against current fixtures.

2. **Phase 2**: expose Kraken seg `threshold` / `min_length` as config fields,
   default them to GM's recommended (0.10 / 100) for charter-style work. This
   alone will likely move CER several points. **Status:** defaults and wiring
   are in [`Settings`](../src/transcriber_shell/config.py) and Kraken/GM-local
   callers; confirm behavior on any lineation path that does not use local BLLA
   (e.g. GM website fallback).

3. **Phase 3**: add the `llm-correct` mode with a short corrective prompt.
   Wire to existing `run_transcribe` with a different system prompt.

4. **Phase 4**: GUI rewrite — the row-per-module layout. Old collapsibles
   become "advanced" of each row's ⚙ panel.

5. **Phase 5**: language detection module with optional VLM backend. This is
   the smallest-impact piece and can land last.

## What this fixes

- **"Where is X?"** — five rows replace ten collapsibles. The default screen
  shows the whole pipeline.
- **"My results are bad"** — when each stage is independently toggleable and
  its draft is exposed, you can immediately see which stage produced bad
  output. Currently HTR output is buried in `htr_results` of the
  `PipelineResult`.
- **"Why is this so slow?"** — each module reports its own timing. Already
  half-collected in `PipelineResult.timings`; surface it per-module.
- **Vendor lock-in** — adding a new HTR backend today means editing
  `build_htr_tasks`, `selector.py`, `gui.py`, `config.py`. Modules collapse
  this to: implement `PipelineModule`, register in a list.

## Open questions

- Do we vendor the GM kraken fork (for exposed seg thresholds) or upstream a
  patch? The fork is GPL-3.0 — same license as GM, so vendoring is fine.
- Should `output` formats be plug-in style or fixed enum? Plug-in is cleaner
  but YAGNI; start with fixed enum.
- The `language-detect` module is the most speculative — keyword-on-prompt is
  what we have today and works. The VLM backend is a nice-to-have but adds an
  extra LLM call. Maybe make it opt-in only.
