# Diplomatic Ground Truth

Human-produced **diplomatic** transcriptions used for expanded-vs-expanded (ex vs ex) evaluation.

Unlike the expanded PAGE XMLs in `ground_truth/pages/`, these preserve the original
abbreviation marks exactly as written, using the same Unicode combining-character
conventions as the pipeline output.

---

## Purpose

The pipeline produces **diplomatic** YAML (abbreviations as Unicode combining chars).
Evaluating that output directly against expanded GT gives meaningless CER (~60%)
because `p̃` ≠ `per`. The correct comparison is:

```
expand(pipeline_diplomatic)  vs  expand(human_diplomatic)
```

Both sides run through the same expand-diplomatic model, so the only variable
is transcription quality — not abbreviation convention.

---

## Format

Each case has two files:

| File | Description |
|------|-------------|
| `{stem}_diplomatic.txt` | Plain text, one TextLine per line, diplomatic Unicode |
| `{stem}_meta.yaml` | Metadata: image, line count, annotator, date, document info |

### `_diplomatic.txt` conventions

- One line per TextLine (must match GT XML line count exactly)
- Abbreviation marks as Unicode combining characters:
  - macron suspension: U+0305 combining overline (e.g., `cōm`)
  - tilde suspension: U+0303 combining tilde (e.g., `p̃` = per/pre)
  - superscript letters written inline after base char (e.g., `wt` with raised `t`)
  - pilcrow `¶` preserved where present
- Uncertain readings: `[uncertain: X / Y]` — first reading is preferred
- Illegible: `[illegible]`
- Line-internal damage: `[damaged: note]`
- Do NOT expand abbreviations — that is the expand-diplomatic step's job

### `_meta.yaml` conventions

```yaml
stem: JUST1-633m5
image: JUST1-633m5.jpeg
line_count: 67
annotator: "Seth Strickland"
date: "2025-05-12"
document:
  repository: TNA
  series: JUST1
  membrane: 633
  entry: m5
  type: eyre_roll
  language: lat-Latn
  era: 1279-1280
  script: anglicana_cursiva
notes: ""
```

---

## Adding a new case

1. Transcribe the page diplomatically — one line per TextLine from the GT XML
2. Save as `ground_truth/diplomatic/{stem}_diplomatic.txt`
3. Save metadata as `ground_truth/diplomatic/{stem}_meta.yaml`
4. Validate line count matches GT XML:
   ```bash
   python3 scripts/latin_ms/validate_diplomatic_gt.py ground_truth/diplomatic/{stem}
   ```
5. Run ex-vs-ex comparison:
   ```bash
   LATIN_MS_JOB_ID={job} LATIN_MS_GT_STEM={stem} bash scripts/latin_ms/s8_compare_expanded.sh
   ```

---

## Cases

| Stem | Lines | Annotator | Date | Document |
|------|-------|-----------|------|----------|
| *(add rows as cases are contributed)* | | | | |
