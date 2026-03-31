# Ground truth storage (human PAGE XML)

Place **human-produced** lineation here (or mirror this layout elsewhere). Do **not** commit large binary corpora unless your repo policy allows it; use Git LFS, DVC, or external storage + manifests.

## Layout

```
ground_truth/
  README.md          (this file)
  pages/             (optional)
    <stem>.png       (or .jpg)
    <stem>.xml       (PAGE XML with TextLine / Baseline@points)
```

- **`&lt;stem&gt;`** must match between image and XML.
- **`Page@imageWidth` / `imageHeight`** must match the image file.

## Quality control

1. **Validate** before accepting a page:

   ```bash
   transcriber-shell validate-gt-pagexml ground_truth/pages/foo.xml ground_truth/pages/foo.png
   ```

2. **Second pass:** Re-review **10–20%** of pages at random plus **any** page that failed validation or has suspicious line counts.

3. **Inter-annotator:** On a pilot set, have two annotators independently line the same crops; run `compare-lines-xml` between their exports to measure disagreement (same `--centroid-match-px` as GM calibration).

## Documentation

- Annotation rules: [docs/ground-truth-human-annotation.md](../docs/ground-truth-human-annotation.md)
- GM calibration workflow: [docs/ground-truth-calibration.md](../docs/ground-truth-calibration.md)

## Git

The `pages/` directory is intentionally empty in git; add images/XML per your data policy.
