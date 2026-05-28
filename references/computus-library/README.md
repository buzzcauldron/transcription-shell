# Computus manuscript library

Unified catalogue for Carolingian **computus** transcription work: the [CitCA](https://computus.huma-num.fr/mss/list) corpus plus local witnesses (Tours 746, Morgan M.925, etc.).

| File | Purpose |
|------|---------|
| [`manifest.json`](manifest.json) | Machine-readable union of all manuscripts |
| [`../computus.bib`](../computus.bib) | Zotero bibliography subset |
| [`../computus-manuscript-map.md`](../computus-manuscript-map.md) | Human-readable map and priorities |

## Refresh CitCA catalogue

```bash
python3 scripts/computus/crawl_citca_catalogue.py
```

Crawls [computus.huma-num.fr/mss/list](https://computus.huma-num.fr/mss/list) (47 MSS), extracts metadata, indexed texts, and **Archive Ms. Page** URLs for strigil.

## Acquire images with strigil

Requires [strigil](https://github.com/sethstrickland/strigil) on `PATH`.

```bash
# Preview
./scripts/computus/acquire_library.sh --dry-run

# One manuscript (Gallica / IIIF example)
./scripts/computus/acquire_library.sh BNF_LAT_2796_COD

# All entries with archive_ms_page
./scripts/computus/acquire_library.sh
```

Images land in `references/computus-library/images/<id>/`. Tours 746 uses `local_image_root` in the manifest (Dropbox path) and is skipped by acquire.

Wire a downloaded witness into the latin_ms pipeline:

```bash
export LATIN_MS_JOB_ID=bnf_lat_2796
export LATIN_MS_SOURCES="references/computus-library/images/BNF_LAT_2796_COD"
# … or copy/symlink into jobs/$LATIN_MS_JOB_ID/00_sources and run s2_crop.sh onward
```

## Manifest fields

- `source`: `citca` | `local`
- `citca_url`: CitCA detail page
- `archive_ms_page`: institutional scan URL for strigil
- `strigil_acquire`: `true` when `archive_ms_page` is set
- `texts`: computistical texts with folio refs (from CitCA)
- `doc_type`: `computus_medieval_latin` for transcription-shell
