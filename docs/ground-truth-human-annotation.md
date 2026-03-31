# Human lineation ground truth (GM-comparable)

Use this guide when drawing **baselines** for manuscript pages so exports match what **transcriber-shell** and **Glyph Machina** comparisons expect: **PAGE-XML** with `TextLine` / **`Baseline@points`** in **page pixel coordinates**.

## Recommended tools (export to PAGE XML)

| Tool | Notes |
|------|--------|
| **[eScriptorium](https://escriptorium.github.io/)** | Kraken-based layout; draw lines, export PAGE. Good fit if you already use Kraken. |
| **[Transkribus](https://transkribus.eu/)** | Layout / baselines; export PAGE. Strong for team workflows and projects. |
| **Glyph Machina** (browser) | Use only as a **reference** or for **calibration**—not a substitute for your own policy on edge cases. See [glyph-machina-automation.md](glyph-machina-automation.md). |

Export **polylines** (`Baseline@points`), not only bounding boxes, so metrics align with [`compare-lines-xml`](../README.md) (Chamfer on baselines).

## File naming

- One **pre-cropped** raster per page: `&lt;stem&gt;.png` or `.jpg`.
- One PAGE file: **`&lt;stem&gt;.xml`** beside the image (same stem).
- **`Page@imageWidth` and `Page@imageHeight`** must equal the image’s pixel width and height (validators and GM comparison assume this).

## Lineation rules (1 page)

1. **Reading order** — Emit `TextLine` elements in **top-to-bottom**, then **left-to-right** order within each logical block (main column first; then marginalia if you include it as separate lines).
2. **One visual line = one `TextLine`** — A line of text from left margin to right (or to where the manuscript ends). Do **not** split a single handwritten line into two because of descenders unless your project policy says otherwise.
3. **Large initials / drop caps** — Include the decorative letter in the **same** `TextLine` as the rest of the first line of that paragraph if it sits on one baseline band; if the initial occupies a **separate** vertical band with no shared baseline with the following text, you may use a separate `TextLine` with its own baseline along the bottom of the initial (document the choice in your project README).
4. **Hyphenation** — Words broken across lines: baseline follows the **ink**; typically **one line per manuscript line**, not one line per lexical word.
5. **Marginalia** — If annotating (e.g. “Everett to Fairbanks” in the margin): either **separate `TextLine`s** in reading order for that strip, or **exclude** marginalia from GT—**pick one** and keep it consistent across the corpus.
6. **Signatures / attestations** — Each distinct signature line or attestation line gets its own `TextLine` with a baseline under the ink, same as body text.
7. **Printed + handwritten mix** — Baselines follow the **text line** whether type or script; do not merge unrelated printed headers with body lines unless they share one line of ink.

**Glyph Machina** behavior may differ on edge cases; your written policy is authoritative for **human** GT. Use [ground-truth-calibration.md](ground-truth-calibration.md) to measure agreement with GM on a **calibration** subset and refine these rules.

## Pipeline use

Supply GT as **`--lines-xml`** with **`--skip-gm`** (single page) or **`--lines-xml-dir`** (batch). See [README](../README.md) and [local-setup.md](local-setup.md).

## Validate before merge

```bash
transcriber-shell validate-gt-pagexml path/to/page.xml path/to/page.png
```

Minimal PAGE skeleton: [`fixtures/ground_truth_page.example.xml`](../fixtures/ground_truth_page.example.xml).

See [ground_truth/README.md](../ground_truth/README.md) for folder layout and QC.
