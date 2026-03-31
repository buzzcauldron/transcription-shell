# Calibration: human GT vs Glyph Machina

Use a **small fixed set** of crops to align annotators with each other and to quantify how close your **human** PAGE XML is to **Glyph Machina** exports—without treating GM as the only truth. See [ground-truth-human-annotation.md](ground-truth-human-annotation.md) for lineation rules.

## Steps

1. **Choose N pages** (e.g. 20–50): mix easy and hard (mixed print/handwriting, marginalia, noise, signatures).
2. **Pre-crop** images to the same inputs you will use in production (fixed dimensions per crop).
3. For each crop:
   - **Human:** Finalize `stem.xml` per your annotation guide.
   - **GM:** Run automated download once per image, e.g. `python scripts/gm_smoke_test.py path/to/stem.png job_id` or the pipeline with `lineation_backend=glyph_machina`, and save the downloaded XML as `stem-gm.xml` (or under `artifacts/…`).
4. **Compare** (same pixel dimensions for both files):

   ```bash
   # Human as reference, GM as hypothesis (how well does GM match human?)
   transcriber-shell compare-lines-xml -r human.xml -y gm.xml --centroid-match-px 120

   # Swap roles to see the symmetric effect on metrics
   transcriber-shell compare-lines-xml -r gm.xml -y human.xml --centroid-match-px 120
   ```

5. **Tune `--centroid-match-px`** — Start at **120**; lower if baselines are tightly registered, higher if exports differ in scale or crop alignment.
6. **Iterate** the annotation guide where **line counts** or **matched pairs** systematically disagree (e.g. marginalia, initials).

## What to record

- Per page: `reference_lines`, `hypothesis_lines`, `matched_pairs`, `recall_vs_reference`, `precision_vs_reference`, `mean_chamfer_px` (from the report).
- Optional: `--json` on `compare-lines-xml` for spreadsheets.

## Limits

- **Terms of use:** Automated GM access should stay within site policy; see [glyph-machina-automation.md](glyph-machina-automation.md).
- **Calibration ≠ full corpus:** Run GM only on the calibration subset unless you have permission for broader automation.
