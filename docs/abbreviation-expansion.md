# Medieval Latin abbreviation expansion (normalized mode)

Use this reference when `normalizationMode = normalized` (the GUI **Diplomatic**
checkbox is unchecked). The output must be readable Latin with abbreviations
expanded into the underlying word and diacritics dropped.

## Operating rule

Every glyph carrying an abbreviation mark in the HTR draft must be **expanded
to its full Latin word** in the final transcription. The reader of the
normalized output should not see `ẽt`, `p̃benda`, `q̃d`, or `m̃` — they should
see `et`, `prebenda`, `quod`, `mm`/`mn`/etc.

The `text` field of each segment is the **expanded** form. Do not leave any
abbreviation glyph in the normalized output. Diacritics added by the scribe to
mark abbreviation (tilde, macron, suspension stroke, superscript) are removed
once the expansion is supplied. Diacritics that are **part of the letter** in
modern Latin orthography (none, in classical/medieval Latin) are not relevant
here.

## Common expansions

### Suspension stroke / tilde over vowel
The tilde or macron stands in for a following **m** or **n**.

| Glyph | Expansion (context-sensitive) |
|---|---|
| `ã` | `am` or `an` |
| `ẽ` | `em` or `en` |
| `ĩ` | `im` or `in` |
| `õ` | `om` or `on` |
| `ũ` | `um` or `un` |
| `m̃`, `n̄` | `mm` / `mn` / `nm` / `nn` (read both sides) |
| `q̃` standing alone | `que` (enclitic conjunction) |
| `ñ` | usually `non`; sometimes `nn` |

### Latin `et` / Tironian et
| Glyph | Expansion |
|---|---|
| `ẽt`, `ẽt̃` | `et` |
| `&`, `⁊` (Tironian) | `et` |
| `ϟ`, `7` (when used as Tironian) | `et` |

### `p` ligatures (very common in legal Latin)
The `p` with a stroke or hook stands for `per` / `par` / `pre` / `pro`. Choose
by what word makes sense:

| Glyph | Most likely expansions |
|---|---|
| `p̃`, `ꝑ` (p with stroke through descender) | `per` (general); `par-` (as in `paratus`); read context |
| `p̄` (p with macron) | `pre-` (as in `prebenda`, `prelati`) |
| `ꝓ` (p with hooked descender) | `pro` (as in `provincia`, `pronunciat`) |
| `p̾` (p with curl above) | `pre-` or `pri-` |

Common full words: `p̃benda → prebenda`, `p̃dcã → predicta`, `p̃ueãũ → provenientium`, `p̃roncs → proventus`.

### `q` ligatures
| Glyph | Expansion |
|---|---|
| `q̃d`, `q̄d` | `quod` |
| `q̃ui`, `q̇ui` | `qui` |
| `q̃m̃`, `q̄m` | `quam` or `quoniam` (context) |
| `q̃o`, `q̄o` | `quo` |
| `q̃ue` standalone | `que` |
| `q̃ualit̃m̃q̃` | `qualitercumque` |

### Suspension marks ending words
A bar over the final letter (or above the line) often means dropped letters.

| Glyph | Expansion |
|---|---|
| `d̃c̃o`, `d̃ic̃o` | `dicto` / `dictum` |
| `d̃no` | `domino` |
| `d̃co`, `d̃cã` | `dicto` / `dicta` / `dictum` |
| `R̃p̃r̃yit̃` | `respondebit` / `respondet` (read carefully) |
| `m̃ñdano` | usually a corruption of `mandando` or `machinans`; cross-check |
| `c̃ompositum` | full word from context |

### Long-s and round-r
| Glyph | Expansion |
|---|---|
| `ſ` (long s) | `s` |
| `ꝛ` (round r) | `r` |
| `ꝯ` (com/con/cum) | `com` / `con` / `cum` per context |

### Suspended endings on common Latin words
| Glyph | Expansion |
|---|---|
| `dn̄o`, `d̃no` | `domino` |
| `dn̄a` | `domina` |
| `ds̄`, `d̄s` | `deus` / `deum` |
| `ihu`, `ihs` | `iesus` (i.e., name of Jesus) |
| `xpc`, `xpi` | `christus`, `christi` |
| `ec̃cl`, `ec̃clie` | `ecclesia`, `ecclesie` |
| `R̃x`, `r̄ex` | `rex` |
| `R̃is`, `R̃ego`, `Regio` (when over-marked) | `regis`, `regem`, `regio` |
| `b̃tus` | `beatus` |
| `f̃r̃e`, `f̃r̃is` | `frater`, `fratris` |
| `m̃gnus` | `magnus` |
| `s̃ce`, `s̃cum`, `s̃ci` | `sancte`, `sanctum`, `sancti` |

### `-bus`, `-rum`, `-tur`, `-ur` endings
| Glyph | Expansion |
|---|---|
| `-bʒ` | `-bus` |
| `-rũ` with stroke | `-rum` (`hospital̃rũ → hospitalium` / `hospitalorum`) |
| `-t̃r`, `-tʒ` | `-tur` |
| `ɑ҃` (a with stroke), `s with curl` | `-rum`, `-orum`, `-arum` |

## What to do when ambiguous

1. **Choose the expansion that yields a real Latin word.** If two are possible
   (e.g. `am` vs `an` for `ã`), choose the one supported by surrounding
   morphology.
2. **Do not invent.** If the abbreviation glyph cannot be expanded to a known
   Latin word, leave the underlying letters and emit a `disambiguation` note
   on that segment rather than a wrong guess.
3. **Cross-check both HTR drafts** if present. When `gm-htr` and `kraken-htr`
   disagree, the LLM should pick the reading that produces sensible Latin
   given the case/declension expected by surrounding words.

## Diacritics on the output

After expansion, the segment `text` should contain only ASCII Latin letters
plus standard punctuation (`. , : ; ? — — — ( )`) and any *macrons* or
*breves* explicitly marking vowel length **only if the source manuscript marks
them as a feature, not as an abbreviation**. In practice for charter Latin,
expanded output is plain ASCII.

## Example: before vs after

**Source HTR draft (kraken raw)**:
> `Johcs vicariʒ ec̃clie de Bann̄ebury attac̃iat̃ f̃t ad ñpoñdendũ d̃no Regi de placito q̃uare cũ idem d̃no R̃x`

**Diplomatic (`normalizationMode = diplomatic`, abbreviations preserved)**:
> Johcs vicariʒ ec̃clie de Bann̄ebury attac̃iat̃ f̃t ad ñpoñdendũ d̃no Regi de placito q̃uare cũ idem d̃no R̃x

**Normalized (`normalizationMode = normalized`, this document applies)**:
> Johannes vicarius ecclesie de Bannebury attachiatus fuit ad respondendum domino Regi de placito quare cum idem dominus Rex
