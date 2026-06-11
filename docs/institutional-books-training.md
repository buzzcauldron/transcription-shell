# Institutional Books 1.0 (HF paper 2506.08300)

[Institutional Books 1.0](https://huggingface.co/papers/2506.08300) catalogs ~983k Harvard Google Books volumes. **Page scans are not on Hugging Face** — they are on **[Internet Archive](https://archive.org)** (IIIF). Hugging Face carries metadata (open) and optional per-page OCR text (gated).

## Recommended pipeline (Internet Archive)

| Step | Source | Tool |
|------|--------|------|
| Filter volumes | HF metadata (open) | `historical-ocr tess fetch --source institutional-books` |
| Page JPEGs | **archive.org** IIIF | `--archive-org` |
| Line GT text | HF `text_by_page_*` (optional) | automatic when `hf auth login` |
| Tesseract train | tesstrain | `historical-ocr tess prepare` + `train-gt` |

```bash
# Local
./scripts/train_institutional_books_ia.sh all

# Bridges
bash scripts/submit_bridges_institutional_books_ia.sh
```

Defaults: **Latin** in `language_distribution_gen`, published **before 1800**, OCR ≥ 80, 30 volumes × 30 IA pages.

Override:

```bash
IB_LIMIT=100 IB_MAX_PAGES=40 HF_TOKEN=hf_... ./scripts/train_institutional_books_ia.sh fetch
```

IA resolution uses HTID (`hvd.<barcode>`), OCLC, LCCN, and title/year Solr queries (`historical_ocr.ml.archive_org`).

## What not to use

| Approach | Problem |
|----------|---------|
| HF text dump only | No page images → not tesstrain/Kraken-ready |
| HathiTrust viewer | Fine for humans; training uses IA IIIF URLs |

## Hugging Face roles

- **`institutional/institutional-books-1.0-metadata`** — filter catalog (no login)
- **`institutional/institutional-books-1.0`** — optional `text_by_page_src` / `text_by_page_gen` for line GT when paired with IA scans (login + license)

Latin volumes only have **source** OCR on HF; post-processed text is eng/deu/fra/ita/spa only.

## Complementary corpora

- **Line-image print OCR (primary):** [tesseract-pre1800-training.md](tesseract-pre1800-training.md) (GT4HistOCR)
- **Manuscript HTR:** `regularize_latin_htr_corpus.py`

## License

IDI early-access terms: **noncommercial**, no redistribution of raw OCR. Keep corpora on local/Bridges storage; cite IDI/Harvard in publications.
