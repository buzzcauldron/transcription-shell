# Harvest signal layers

Generated: 2026-08-13T13:48:56.940084+00:00

Books containing computus are treated as **genre-mixed miscellanies**.
Layers report primary+secondary (or a distribution), never one forced label.

## Layer catalog

| id | tool | status | signal |
|---|---|---|---|
| `holdings` | computus.lat + union registry | computed | holding-library geography and confirmed digitization URLs |
| `citca_origin` | CitCA manifest | computed | origin region and century for 54 dated witnesses only |
| `title_genre` | transcriber_shell.stylometry.title_genre | computed | work-title prior (CitCA texts[]); not a book-level genre |
| `discourse_mix` | genre_signal / medieval-proof | computed | rolling primary+secondary discourse; near-ties kept |
| `fingerprint` | stylometry.fingerprint (FW + char n-grams) | computed | book-level style neighborhood without R stylo |
| `dendro_series` | dendro-shell crossdate idea on rolling computus_calendar weight | computed | lag-correlation of mix series between books; not ring detection |
| `layout` | DocLay YOLO (transcriber_shell.figures.doclay) | specified | page mix Table/Text/Picture = compilation strategy |
| `script` | manuscript-fingerprint L0 on PAGE XML | specified | script-family clustering from ink-component heights; skip typebox L1 (print) |
| `keyness` | antconc-engine keyword vs locked historical core | specified | computus-like vs not, without a whole-book genre call |
| `r_stylo` | stylometry-r run_stylo_target.R | partial | harvest jobs clat_107 / clat_114 only; mixed miscellanies |

## CitCA / local (n = 54)

- Indexed works: 203 (unmatched titles: 82)
- Origin buckets: {'Northern / NE France': 16, 'Lake Constance': 11, 'German lands': 8, 'Loire / E. France': 7, 'unknown': 6, 'Italy': 5, 'Southern France': 1}
- Century bins: {'800s': 33, '700s': 12, 'undated': 7, '900s': 2}
- Title-genre prior: {'computus': 53, 'epistolary': 37, 'grammar': 13, 'history': 4, 'natural-philosophy': 4, 'scholastic': 4, 'astronomy': 2, 'exegesis': 2, 'hagiography': 1, 'moral-instruction': 1}

## Core extracts scored (`stylometry-r/output/batch_stylo_texts`, n = 8)

- Near-tie primary/secondary: 0.0
- Primary counts: {'computus_calendar': 6, 'astronomical_technical': 1, 'theological_scholastic': 1}
- Secondary counts: {'astronomical_technical': 5, 'computus_calendar': 2, 'narrative_history': 1}
- Dendro-style mix crossdates (|r| ≥ 0.35, overlap ≥ 6): 20

