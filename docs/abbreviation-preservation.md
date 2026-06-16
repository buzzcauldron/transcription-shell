# Medieval Latin abbreviation preservation (diplomatic mode)

Use this reference when `preserveOriginalAbbreviations = true` (the GUI **Diplomatic**
checkbox is checked). The output must reproduce every abbreviation mark exactly as
visible in the manuscript — the reader sees what the scribe wrote, not what it means.

This document covers diplomatic mode only. For normalized/expanded output see
`abbreviation-expansion.md`.

## Operating rule

Every abbreviation mark in the source (combining diacritic, superscript, suspension
stroke, special letterform) **must appear in the transcription text**. Do not silently
resolve any abbreviation. The HTR draft may have already expanded some marks; if so,
restore them from the image before returning the diplomatic text.

The `text` field of each segment is the **abbreviated** form exactly as written.

## Common marks to preserve

### Suspension stroke / tilde over vowel — do NOT expand
| Manuscript glyph | Preserve as-is |
|---|---|
| ã, ẽ, ĩ, õ, ũ | retain with tilde (U+0303) |
| m̃, ñ | retain with tilde |
| ā, ē, ī, ō, ū | retain with macron (U+0304/U+0305) |
| q̃ | retain — do not write `que` |
| ñ | retain — do not write `non` |

### `p` ligatures — do NOT expand
| Glyph | Preserve |
|---|---|
| p̃, ꝑ | retain as Unicode combining or PUA char |
| p̄ | retain with macron |
| ꝓ | retain |
| p̾ | retain |

Do not write `per`, `pre`, `pro` etc. — those are normalized forms.

### `q` ligatures — do NOT expand
| Glyph | Preserve |
|---|---|
| q̃d, q̄d | retain — do not write `quod` |

### Tironian et / ampersand
| Glyph | Preserve |
|---|---|
| ẽt, ẽt̃ | retain — do not write `et` |
| ⁊ (U+204A), & | retain — do not write `et` |
| 7 used as Tironian | retain as `7` or ⁊ |

### Superscript abbreviation letters
Retain the superscript form using Unicode superscripts where available, or use the
`[superscript: X]` token when no Unicode form exists (layout_aware / diplomatic_plus
profiles only). Do not silently drop or expand.

## Uncertainty and abbreviation
If an abbreviated form is partially illegible, use `[uncertain: X]` with the best
diplomatic reading, **not** the expanded word. For example: `[uncertain: p̃]` not
`[uncertain: per]`.

## Protocol enforcement
The benchmark expansion firewall (`§2.4.1`) scores diplomatic GT against diplomatic
output only. If the model output contains expanded words when
`preserveOriginalAbbreviations: true`, the run is flagged as a protocol violation
and scoring is blocked. The BINDING RULE in the prompt explicitly prohibits expansion
in diplomatic mode.
