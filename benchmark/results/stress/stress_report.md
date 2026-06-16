# Stress test compatibility matrix

Generated: 2026-06-16T17:29:10Z (UTC)

| Case | Model | Schema OK | Accuracy% | Additions | Omissions | Disposition | Notes |
|------|-------|-----------|-----------|-----------|------------|-------------|-------|
| BM-001 | shell-computus-gemini (gemini-2.5-pro) | False | — | — | — | FAIL | ERROR: while parsing a block mapping
  in "<unicode string>", line 40, column 7:
        - segmentId: 1
          ^
expected <block end>, but found '<scalar>'
  in "<unicode string>", line 46, column 9:
            Springfield Aug. 18th 1837
            ^ |
| BM-001 | shell-full-r5-gemini (gemini-2.5-pro) | True | 94.1% | 29 | 29 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-001 | shell-r2-gemini (gemini-2.5-pro) | False | — | — | — | FAIL | ERROR: while parsing a block mapping
  in "<unicode string>", line 38, column 7:
        - segmentId: 1
          ^
expected <block end>, but found '<scalar>'
  in "<unicode string>", line 44, column 9:
            Springfield Aug. 18[superscript: ... 
            ^ |
| BM-001 | shell-r5-gemini (gemini-2.5-pro) | True | 94.5% | 31 | 27 | FAIL | — |
| BM-MED-001 | shell-computus-gemini (gemini-2.5-pro) | True | 72.0% | 31 | 28 | FAIL | — |
| BM-MED-001 | shell-gm-gemini (gemini-2.5-pro) | True | 85.0% | 18 | 15 | FAIL | — |
| BM-MED-001 | shell-r2-gemini (gemini-2.5-pro) | True | 69.0% | 37 | 31 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-MED-001 | shell-r5-gemini (gemini-2.5-pro) | True | 88.0% | 14 | 12 | FAIL | — |
| BM-KB27 | shell-computus-gemini (gemini-2.5-pro) | True | 22.5% | 140 | 193 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-KB27 | shell-full-r2-gemini (gemini-2.5-pro) | True | 23.3% | 185 | 191 | FAIL | — |
| BM-KB27 | shell-gm-gemini (gemini-2.5-pro) | True | 9.2% | 194 | 226 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-KB27 | shell-r2-gemini-3-1-pro-preview (gemini-3.1-pro-preview) | True | 62.2% | 97 | 94 | FAIL | — |
| BM-KB27 | shell-r2-gemini-3-5-flash (gemini-3.5-flash) | True | 55.4% | 110 | 111 | FAIL | — |
| BM-KB27 | shell-r5-gemini (gemini-2.5-pro) | True | 20.5% | 180 | 198 | FAIL | — |
| BM-MOD-LOVEJOY | shell-computus-gemini (gemini-2.5-pro) | False | 82.4% | 4 | 13 | FAIL | missing required field: confidence; missing required field: uncertaintyTokenCount; segment 0 confidence invalid: got None, expected one of ('high', 'medium', 'low') Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-MOD-LOVEJOY | shell-r2-gemini (gemini-2.5-pro) | False | — | — | — | FAIL | ERROR: while parsing a block mapping
  in "<unicode string>", line 38, column 7:
        - segmentId: 1
          ^
expected <block end>, but found '<block mapping start>'
  in "<unicode string>", line 46, column 9:
            Friend Nicolay:
            ^ |
| BM-MOD-LOVEJOY | shell-r5-gemini (gemini-2.5-pro) | True | 81.1% | 3 | 14 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-MOD-JOHNSON | shell-computus-gemini (gemini-2.5-pro) | True | 26.9% | 22 | 49 | FAIL | — |
| BM-MOD-JOHNSON | shell-r2-gemini (gemini-2.5-pro) | True | 26.9% | 21 | 49 | FAIL | — |
| BM-MOD-JOHNSON | shell-r5-gemini (gemini-2.5-pro) | True | 31.3% | 19 | 46 | FAIL | — |
| BM-MOD-DEED | shell-computus-gemini (gemini-2.5-pro) | True | 97.4% | 5 | 2 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-MOD-DEED | shell-full-computus-gemini (gemini-2.5-pro) | True | 96.2% | 5 | 3 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-MOD-DEED | shell-r2-gemini (gemini-2.5-pro) | True | 93.6% | 8 | 5 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbreviation/difficulty, but zero [uncertain] / [illegible] / [glyph-uncertain] tokens — flag for human review |
| BM-MOD-DEED | shell-r5-gemini (gemini-2.5-pro) | True | 92.3% | 7 | 6 | FAIL | — |
| BM-OCR-001 | shell-r2-gemini-3-1-pro-preview (gemini-3.1-pro-preview) | False | — | — | — | FAIL | ERROR: error: --require-text-line set but no TextLine elements found; Lines XML did not pass validation (well-formed XML, TextLine rules, or optional checks). See detailed messages above; try unchecking 'Require ≥1 TextLine' if your file has no TextLine yet, or use --skip-lines-xml-validation / TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION to bypass checks. |
| BM-OCR-001 | shell-r2-gemini-3-5-flash (gemini-3.5-flash) | False | — | — | — | FAIL | ERROR: error: --require-text-line set but no TextLine elements found; Lines XML did not pass validation (well-formed XML, TextLine rules, or optional checks). See detailed messages above; try unchecking 'Require ≥1 TextLine' if your file has no TextLine yet, or use --skip-lines-xml-validation / TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION to bypass checks. |
