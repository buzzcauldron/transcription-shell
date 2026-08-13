# Greek HTR ground truth (ancient + medieval)

Open PAGE/ALTO and line-level corpora for training Greek (polytonic **grc**) recognition and lineation. Latin remains the densest HTR resource; Greek is thinner—especially **true ancient** material (papyri)—so we keep a separate registry and download path so Greek packs are never lost inside Latin-only filters.

## Download

```bash
# Full open set (~0.9+ GB Zenodo + git; Bessarion optional/large)
./scripts/download_greek_htr_corpora.sh

# Skip NC packs (HPGTR, LJS380) and the inscription mega-repo
SKIP_NC=1 SKIP_BESSARION=1 OUT=~/src/htr-corpora-greek \
  ./scripts/download_greek_htr_corpora.sh
```

Default output: `$HOME/src/htr-corpora-greek` (override with `OUT=`).

## Regularize (same tool as Latin)

```bash
python scripts/regularize_latin_htr_corpus.py \
  --registry scripts/greek_htr_corpus_registry.yaml \
  --corpora-root ~/src/htr-corpora-greek \
  --out-dir ~/src/greek-corpus-gt \
  --seed 42
```

## Sources (priority = ancient)

| ID | Era / medium | Approx. volume | License | Notes |
|----|--------------|----------------|---------|--------|
| **zenon-papyri** | 3rd c. BCE papyri | ~321 lines / 27 pages | CC-BY 4.0 | Zenodo 6565706; JPG+PAGE — **best ancient seed** |
| **ancient-greek-transcriboquest-2025** | 4th–1st c. BCE | ~20 pages | CC-BY 4.0 | Zenodo 17062972; Homeric, Menander, medical, P.Eleph. 1 |
| **ljs380-sextus** | classical author / 15c hand | line crops | **CC-BY-NC 4.0** | HF; Bekker-aligned labels |
| **eparchos** | 1500–1530 minuscule | ~120 pages | CC-BY 4.0 | Zenodo 4095301; Psellos etc. |
| **stavronikita-{53,79,114}** | Athos gospels | ~1–2k lines each pack | CC-BY 4.0 | Zenodo 5595669 / 5578136 / 5578251 |
| **palatine-anthology-cpgr23** | 10c codex / classical epigrams | ~3.4k lines | CC-BY 4.0 | GitLab ecrium |
| **hpgtr** | Bodleian Barocci 10–16c | ~1.7–1.9k lines | **CC-BY-NC-SA 3.0** | github.com/vivianpl/hpgtr + `alto.zip` |
| **vat-gr-2228-phil-gr-130** | 14c | 46 PAGE-XML | open annotations | Zenodo 20705757; **images not in zip** — pair via library IIIF |
| **eutyches** | 9c caroline + Greek | Latin + Greek gloss | Apache-2.0 | shared with Latin list |
| **bessarion** | Byzantine inscriptions | large | see repo | domain shift; optional |
| **greekhtr-pta-model** | 9–12c model | model only | mixed | Zenodo model 15838142; IIIF lists, not GT dump |

Citations: [`scripts/htr_corpora.bib`](../scripts/htr_corpora.bib). Machine-readable config: [`scripts/greek_htr_corpus_registry.yaml`](../scripts/greek_htr_corpus_registry.yaml).

## Training notes

1. **Separate Greek corpus tree.** Do not mix Greek and Latin into one Kraken alphabet/model unless you intentionally train a multi-script model; CER will crater on both otherwise. Fine-tune Greek from a Greek or multi-script seed (e.g. PTA Greek minuscule model) rather than from Latin r5/computus alone.
2. **Ancient vs medieval.** Papyri (cursive majuscule / informal documentary hands) ≠ Byzantine minuscule books. Prefer staged training: (a) Athos + EPARCHOS + Palatine for book hands; (b) Zenon + TranscriboQuest for papyri domain; (c) optional Bessarion for layout stress tests.
3. **NC licenses.** HPGTR and LJS380 are non-commercial; use `SKIP_NC=1` or keep them only in research manifests.
4. **Images rights.** Vat. gr. 2228 / Phil. gr. 130 release is geometry (+text) without redistributed images; plan a local IIIF fetch before regularize.
5. **Unicode.** Prefer NFC polytonic; PTA models publish NFC-normalized checkpoints—align transcription rules before merging packs.

## Train on Bridges-2

```bash
# Stage corpora + PTA seed (Zenodo 15838142) + scripts, then sbatch
./scripts/submit_bridges_greek_minuscule.sh

# Or step-wise:
./scripts/rsync_greek_corpora_to_bridges.sh
ssh bridges2 'cd /ocean/projects/hum260002p/sstrickland/transcriber-shell/src && sbatch scripts/r_greek_minuscule_retrain.sbatch'
```

| Piece | Path |
|-------|------|
| Prep (compute) | `scripts/bridges_greek_corpus_prep.sh` → `$SRC/greek-corpus-gt` |
| Manifests | `greek_minuscule_{train,val}_manifest.txt` via `split_greek_manifests.py` |
| Train / resume | `r_greek_minuscule_retrain.sbatch` / `r_greek_minuscule_resume.sbatch` |
| Seed | `$SRC/greek_minuscule_s9-12_NFC.mlmodel` |
| Export | `$SRC/gm-htr-greek-minuscule_best.mlmodel` |

Minuscule ~480/50 pages after pairing (Athos + EPARCHOS + Palatine + HPGTR + Eutyches). Papyrus packs are split separately for a later specialist.

## Related

- Latin corpora: [`scripts/download_htr_corpora.sh`](../scripts/download_htr_corpora.sh), [`docs/MODELS.md`](MODELS.md)
- Human GT layout: [`ground_truth/README.md`](../ground_truth/README.md)
- Protocol language tag for Greek: `ell-Grek` / `grc` in transcription-protocol
