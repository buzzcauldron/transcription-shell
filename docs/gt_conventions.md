# Ground-truth conventions for CER scoring

This project measures pipeline accuracy by running `transcriber-shell score` on
expanded TEI XML against PAGE XML ground truth. For the scores to mean
anything, the GT and the pipeline output have to be in **comparable** form —
not identical, but equivalent after the scorer's `_canonicalize_latin`
normalization (see `src/transcriber_shell/pipeline/score.py`).

This doc describes what to write in a `.gt.txt` template so the resulting CER /
WER numbers reflect transcription quality, not formatting choices.

## Recommended GT style: fully expanded Latin

The TEI expansion stage (5) produces fully expanded medieval Latin in
`<body><p>...</p></body>` elements — `pro`, `nostra`, `episcopo`, etc. with no
abbreviation marks. Your `.gt.txt` should match that form. Reasons:

- Most CER difference between GT and hypothesis should be **real
  transcription errors**, not abbreviation-resolution choices.
- `_canonicalize_latin` already strips combining marks, drops `'`, normalizes
  `u`↔`v` and `i`↔`j`, lowercases — so the GT writer doesn't need to match LLM
  capitalization or punctuation perfectly. **But it does need to match
  abbreviation expansion**, because expansion changes word boundaries and
  character counts.

### Good (expanded)

```
001: pro episcopo Norwicensi et Thesaurario et Baronibus suis de Scaccario salutem
002: consideratum quod omnia temporalia episcopi Norwicensis episcopatus predicti
```

### Avoid (abbreviated)

```
001: p̄ ep̄o Norwic̃ et Thes̃o et Baronibus suis de Sccō salt'm
002: cōsideratū qd ōīa temp̄alia ep̄i Norwic̃ ep̄atus pdc̄i
```

The abbreviated form is more faithful to the manuscript, but it inflates CER
purely from convention mismatch with the expanded pipeline output. If you
need a diplomatic record alongside the GT, keep it as a separate file (e.g.
`<stem>.diplomatic.txt`) and use the expanded form for scoring.

## Filling a template

After `transcriber-shell gt-template`:

```
~/latin-ms-workspace/jobs/<job>/02_lines/
  ├── <stem>.xml
  ├── <stem>.gt.txt          ← numbered template, one line per <TextLine>
  └── <stem>.gt_tiles/       ← per-line PNG crops (if --crop-tiles)
       ├── 001.png
       ├── 002.png
       └── ...
```

Open each `.png` tile, type the expanded Latin transcription on the
corresponding numbered line in `.gt.txt`. Blank lines are skipped by the
scorer (use this when a line is illegible or you want to defer it).

Quote names verbatim (`Iohannes`, `Norff'`, `Suff'`) and trust the scorer's
canonicalization to handle case / u-v / i-j / punctuation — but **do expand
abbreviation marks** (`p̄` → `pro`, `nr̄a` → `nostra`).

When unsure between two readings, pick one. Don't write `[uncertain: A / B]`
in GT — that token vocabulary is for *pipeline output*, not ground truth.

## Inject and score

```bash
# Inject typed text into <TextEquiv><Unicode> of the XML
transcriber-shell gt-inject ~/latin-ms-workspace/jobs/<job>/02_lines/<stem>.xml

# Score the expanded TEI against this GT
transcriber-shell score \
    ~/latin-ms-workspace/jobs/<job>/04_expanded \
    --gt ~/latin-ms-workspace/jobs/<job>/02_lines \
    --report ~/latin-ms-workspace/jobs/<job>/06_scores
```

## Interpreting the CER

- **Absolute CER < 5%**: pipeline output is publication-quality after light
  proofreading.
- **5–15%**: needs paleographic review; structure is correct but glyph errors
  are common.
- **15–30%**: pipeline misses key words (place names, proper nouns, formula
  variants) but gets the overall structure. Typical for first-pass on
  unfamiliar hands.
- **>30%**: pipeline confused; check if the doc-type / model / lineation
  matches the source.

## Caveats

- **Single-page scores are noisy.** Five or more pages with GT is the minimum
  for a meaningful aggregate. Per-page WER also tracks well — if WER on a
  page is >40% the pipeline likely missed sense-bearing words even if CER
  looks OK.
- **WER tied while CER differs** means the same words are wrong but one
  pipeline gets closer letters (e.g. "Gusper" vs "Suff'" — both wrong, but
  one is closer in chars).
