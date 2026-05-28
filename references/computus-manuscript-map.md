# Computus bibliography → manuscripts map

Subset BibTeX: [`computus.bib`](computus.bib) (21 entries, deduplicated from *Computus Project.bib*).

**Unified library (CitCA crawl + local witnesses):** [`computus-library/manifest.json`](computus-library/manifest.json) — refresh with `python3 scripts/computus/crawl_citca_catalogue.py`; acquire scans via `./scripts/computus/acquire_library.sh` (strigil). See [`computus-library/README.md`](computus-library/README.md).

Pipeline doc type for transcription: [`scripts/latin_ms/document_types/computus_medieval_latin.yaml`](../scripts/latin_ms/document_types/computus_medieval_latin.yaml).

---

## Active transcription corpus (not in Zotero export)

| Your project | Shelfmark | In `computus.bib`? | Notes |
|--------------|-----------|-------------------|--------|
| **Tours 746 batch** | Bibliothèque municipale de Tours, MS 746 | In [`manifest.json`](computus-library/manifest.json) as `tours_bm_746` | Primary test corpus on Mac (`--doc-type computus_medieval_latin`). Many diagram/table folios fail Kraken lineation (`text_lines=0`). Not in [CitCA list](https://computus.huma-num.fr/mss/list) (54 witnesses total in manifest). |
| **CMU training GT** | `~/src/computus-gt/` manifests (185k train lines) | No | Ground truth for `gm-htr-computus` HTR fine-tune on akdeniz; sources are separate PageXML corpora, not this bib file. |

---

## Manuscripts in the bibliography (with cite keys)

| Cite key | Shelfmark / witness | Texts / content | Transcription relevance |
|----------|---------------------|-----------------|-------------------------|
| `ComputusCollectionMS` | Morgan Library, **MS M.925** | Computus collection (multiple short texts) | High — Carolingian computus florilegium; compare table/layout handling with Tours 746. |
| `Computus` | BL **Harley MS 3667** | Byrhtferth, *Enchiridion* (computus commentary); famous diagram | High — diagrams + prose; good seg/HTR stress test after models trained. |
| `themonkbyrhtferthByrhtferthsManuscriptMS1111` | Oxford, St John’s College, **MS 17** (*Thorney Computus*, c. 1110) | Full computus album: tables, maps, Byrhtferth diagram | High — same genre as Tours/Morgan; Internet Archive scan linked in bib. |
| `lawrence-mathersReadingComputusManuscriptSt` | Cambridge, St John’s College, **MS A.22** | *Reading Computus* | High — Lawrence-Mathers article is the secondary literature anchor. |
| `ComputisticalMiscellany` | Wellcome Collection ([work x3knvt2r](https://wellcomecollection.org/works/x3knvt2r)) | **Five computi:** (1–2) *Computus chirometralis* minor/maior (John of Erfurt); (3) tables; (4) Peter of Dacia, *Tabulae cum explicationibus*; (5) *Computus judaicus* | High — matches `prompt_computus.yaml` vocabulary (chirometralis, tables). |
| `ComputusText3` | NYPL Digital Collections, “Computus, Text 3” | Single computus text witness | Medium — check NYPL for full shelfmark when downloading images. |
| `burrComputusCirometralis1438` | Edition: *Computus cirometralis* (Ars Computistica) | Printed/edited witness, not a single MS | Medium — textual reference for chirometralis genre (cf. Wellcome MS). |
| `LostSirmondManuscript` | Bede, *De temporum ratione* / **Computus** (Sirmond recension) | Lost manuscript tradition | Low for images — literary/textual history; CELT/JSTOR links in bib. |
| `MedievalManuscriptComputational1857` | Raab catalogue entry | “Computational cipher computus” | Low — catalogue snippet; verify identity before imaging. |

---

## Text editions & corpora (no single shelfmark)

| Cite key | What it is | Use |
|----------|------------|-----|
| `warntjesMunichComputusText2010` | Edition/translation: **Munich Computus** (Irish computistics, Carolingian reception) | Primary scholarly edition; compare readings against HTR/LLM output. |
| `warntjesComputusScientificThought2016` | Essay on computus as scientific thought | Context for doc-type prompt. |
| `thorndikeComputus1954` | Thorndike, *Speculum* article “Computus” | Historiography (`ComputusSpeculumVol` is the journal landing page). |
| `mosshammer1Introduction2008`, `mosshammer2ChronologicalSystems2008`, `mosshammer78YearCycle2008` | Chapters from *The Easter Computus and the Origins of the Christian Era* | Paschal chronology, Dionysius, epacts — informs table columns in MSS. |
| `EasterComputusOrigins` | Oxford Academic link to Mosshammer book | Same book, online access. |
| `ControversiaPaschali` | CELT: *De controversia paschali* | Paschal controversy text (Latin), not a computus MS. |

---

## Catalogues & discovery tools

| Cite key | URL | Use for Tours 746 / new MSS |
|----------|-----|------------------------------|
| `Computuslat2023` | [computus.lat](https://thomsnijders.nl/computus-lat/) | Search by library/city; find computistical contents and figura types. |
| `ComputusCarolingianAge` | [computus.huma-num.fr](https://computus.huma-num.fr/) | Carolingian computus MSS list + bibliography. |
| `BrepolsOperaComputo` | Brepols *Opera de computo saeculi XII* | 12th-c. edited computus texts for collation. |

---

## Individual computi inside `ComputisticalMiscellany`

These are **text titles** within one manuscript (Wellcome), not separate bib entries:

1. John of Erfurt — *Computus chirometralis minor* (ff. 1r–8r)
2. *Computus chirometralis* maior (ff. 8r–16r)
3. Tables (ff. 16v–17r)
4. Peter of Dacia — *Tabulae cum explicationibus* (ff. 17v–18r)
5. *Computus judaicus* (ff. 19v–22v; copied 1443)

---

## Suggested next imaging / batch targets

Priority order if expanding beyond Tours 746:

1. **Morgan M.925** — same genre, Morgan has IIIF; cite `ComputusCollectionMS`.
2. **Cambridge St John’s A.22** — Reading Computus; article in hand (`lawrence-mathersReadingComputusManuscriptSt`).
3. **Oxford St John’s MS 17** — Thorney/Byrhtferth album; Archive.org scan in bib.
4. **Wellcome computistical miscellany** — short German-hand codex with named chirometralis texts.
5. **BL Harley 3667** — Byrhtferth diagram pages (hard segmentation; good after `kraken-finetuned` / computus seg).

---

## Cite in writing

```bibtex
@comment{See transcription-shell/references/computus.bib}
```

For Zotero, import `references/computus.bib` or keep the master file at `~/Downloads/Computus Project.bib`.
