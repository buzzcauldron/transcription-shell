# HTR / segmentation model registry

One YAML per trained model. The model registry (`src/transcriber_shell/htr/model_registry.py`) reads this directory and lets callers pick a model either by exact `name:` or by **language + era + script criteria** — so a doc-type that says "Latin / early modern / humanist_italic_mixed" can resolve to whichever model on disk covers that profile best.

## Spec fields

```yaml
name: gm-htr-r2_best                          # unique slug, used as --htr-model NAME
kind: htr                                     # htr | segmentation
path: "${HOME}/src/latin_documents/gm-htr-r2.mlmodel_best.mlmodel"
size_mb: 24

# What this model can transcribe — used by the selector to rank candidates.
languages: [lat-Latn, fra-Latn, eng-Latn]     # IETF BCP-47 with -Latn script tag
eras: [medieval, early_modern]                # canonical era tags (see protocol)
scripts: [anglicana_cursiva, gothic_cursiva, humanist_italic_mixed]
era_range: "1280-1700"                        # human-readable range; informational

# How it was trained (frozen at training time so we can diff rounds).
training:
  base_model: gm-hf-htr_best
  round: 2
  date: 2026-05-11
  corpora: [catmus-medieval, tridis, cremma-medieval, glyph-machina]
  hyperparams:
    learning_rate: 0.00005
    batch_size: 16
    epochs_run: 50
    augment: true
    schedule: reduceonplateau

# Validation metrics. Re-populate by running `transcriber-shell score-htr-per-corpus`.
metrics:
  val_accuracy: 0.841
  val_word_accuracy: 0.522
  per_corpus_cer: {}                          # filled in by score-htr-per-corpus
  notes: "Trimmed train set; r2 best at epoch ~50."
```

## Selection rules

The selector ranks models by overlap of (language, era, script) with the doc-type criteria, then by training round number (higher wins), then by per-corpus CER when available (lower wins). Use `transcriber-shell list-htr-models` to see the current ranking on disk.
