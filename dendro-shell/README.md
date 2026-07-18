# dendro-shell

Path-first tree-ring tracing for difficult cores and discs: hard-image preprocess presets, interactive measure/review UI, chronology exports (`.rwl` / `.pos` / JSON), and **in-app U-Net training**.

Inspired by [TRAS](https://github.com/hmarichal93/tras), [TRG-ImageProcessing](https://github.com/Gregor-Mendel-Institute/TRG-ImageProcessing), and [MtreeRing](https://github.com/ropensci/MtreeRing) — not a GPL fork. Preprocess and review patterns follow transcription-shell / historical OCR habits (named presets, path-neighborhood enhancement, human-in-the-loop correction).

## Install

```bash
cd dendro-shell
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[ui,train,dev]"
```

No conda. Classical detect runs on CPU; training uses PyTorch when the `train` extra is installed.

## Launch

```bash
# Browser UI (measure + Train panel)
dendro open
dendro open path/to/core.tif

# CLI detect → project.json + rwl + pos + overlay
dendro detect path/to/core.png -o out/ --preset sanded_core --outer-year 2024

# Train from library (same job runner as the UI)
dendro train --library ~/DendroLibrary --epochs 30 --imgsz 512

# Add a corrected project.json to the training library
dendro library-add out/project.json

# Crossdate against a master chronology
dendro crossdate out/project.json master.rwl
```

Open the UI at [http://127.0.0.1:8765](http://127.0.0.1:8765).

## Workflow

1. **Open** a core or disc image.
2. Pick a **preprocess preset** (`sanded_core`, `dark_disc`, `wet_stain`, `narrow_rings`).
3. Draw a **measurement path** (or use the default mid-line / radial path). For discs: **Estimate pith** or Alt+click.
4. **Detect** (classical peaks or active U-Net). Edit ticks: drag, `A` add, `D` delete, `M` missing, `F` false.
5. Set **outer year** and **µm/px** scale; export `.rwl` / `.pos`.
6. **Add to training set** → **Train** panel → activate checkpoint → detect with U-Net.

```text
image → preset → detect → path ticks → edit → series → rwl/pos
                              ↓
                        training library → in-app train → active model
```

## Presets

| Preset | Use when |
|--------|----------|
| `sanded_core` | Clean sanded cores (CLAHE + mild unsharp) |
| `dark_disc` | Dark / underexposed discs (invert + strong CLAHE) |
| `wet_stain` | Stain / blotch noise (median + morph open) |
| `narrow_rings` | Packed rings (strong unsharp + high-frequency boost) |

## Training (in-software)

Corrected projects are ground truth. The Train panel (and `dendro train`) share `dendro_shell.train.job.run_training`:

- Library default: `~/DendroLibrary` (`DENDRO_LIBRARY` to override)
- Checkpoints: `~/.cache/dendro-shell/models/` with `manifest.json`
- Fine-tunes from the active checkpoint when present
- Progress via `/api/train/status` (UI polls); never blocks measuring

Practical start: 20–50 corrected path samples, `imgsz` 256–512, CPU OK for small runs.

## Visuals

- **Measure canvas** — confidence-sized ticks, year labels, pith marker
- **Ring zoom strip** — contact sheet of per-ring crops (comma_review style)
- **Timeline** — widths + decade years + missing markers + skeleton stems
- **Viz tab** — growth bars, skeleton plot, classical vs U-Net compare overlay
- **Export also writes** `skeleton.png` and stacked `report.png`

## Exports

- **Tucson `.rwl`** — ring-width series
- **CooRecorder-style `.pos`** — path tick coordinates + scale
- **`project.json`** — full editable state
- **`overlay.png`** — confidence-styled path + ticks
- **`skeleton.png` / `report.png`** — chronology figures

## Tests

```bash
pytest -q
```

## Layout

```text
src/dendro_shell/
  preprocess.py   # OCR-style presets
  geometry.py     # pith, paths, polar unwrap, scale
  detect/         # classical + U-Net
  series.py       # widths, years, incline
  export/         # rwl, pos, overlay, json
  crossdate.py    # light reference correlator
  train/          # dataset, TinyUNet, job, registry
  ui/             # FastAPI + static measure/train UI
  cli.py          # dendro entry point
```

## License

MIT
