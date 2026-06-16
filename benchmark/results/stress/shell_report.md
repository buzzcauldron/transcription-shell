# transcriber-shell pipeline benchmark results

Generated: 2026-06-10T19:42:11Z (UTC)

These results were produced by the full transcriber-shell pipeline (HTR draft + LLM correct-mode),
compared against the image-only baseline in the
[transcription-protocol benchmark](https://github.com/buzzcauldron/transcription-protocol/tree/main/benchmark/test-results/stress/).

| Case | Model | Schema OK | Accuracy% | Additions | Omissions | Disposition | Notes |
|------|-------|-----------|-----------|-----------|------------|-------------|-------|
| BM-001 | shell-computus-gemini (gemini-2.5-pro) | False | — | — | — | FAIL | ERROR: while parsing a block mapping   in "<unicode string>", line 40, column 7:         - segmentId: 1           ^ expe |
| BM-001 | shell-full-r5-gemini (gemini-2.5-pro) | True | — | 29 | 29 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-001 | shell-r2-gemini (gemini-2.5-pro) | False | — | — | — | FAIL | ERROR: while parsing a block mapping   in "<unicode string>", line 38, column 7:         - segmentId: 1           ^ expe |
| BM-001 | shell-r5-gemini (gemini-2.5-pro) | True | — | 31 | 27 | FAIL | — |
| BM-MED-001 | shell-computus-gemini (gemini-2.5-pro) | True | — | 31 | 28 | FAIL | — |
| BM-MED-001 | shell-gm-gemini (gemini-2.5-pro) | True | — | 18 | 15 | FAIL | — |
| BM-MED-001 | shell-r2-gemini (gemini-2.5-pro) | True | — | 37 | 31 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-MED-001 | shell-r5-gemini (gemini-2.5-pro) | True | — | 14 | 12 | FAIL | — |
| BM-KB27 | shell-computus-gemini (gemini-2.5-pro) | True | — | 140 | 193 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-KB27 | shell-full-r2-gemini (gemini-2.5-pro) | True | — | 185 | 191 | FAIL | — |
| BM-KB27 | shell-gm-gemini (gemini-2.5-pro) | True | — | 194 | 226 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-KB27 | shell-r2-gemini (gemini-2.5-pro) | True | — | 158 | 182 | FAIL | — |
| BM-KB27 | shell-r5-gemini (gemini-2.5-pro) | True | — | 180 | 198 | FAIL | — |
| BM-MOD-LOVEJOY | shell-computus-gemini (gemini-2.5-pro) | False | — | 4 | 13 | FAIL | missing required field: confidence; missing required field: uncertaintyTokenCount; segment 0 confidence invalid: got Non |
| BM-MOD-LOVEJOY | shell-r2-gemini (gemini-2.5-pro) | False | — | — | — | FAIL | ERROR: while parsing a block mapping   in "<unicode string>", line 38, column 7:         - segmentId: 1           ^ expe |
| BM-MOD-LOVEJOY | shell-r5-gemini (gemini-2.5-pro) | True | — | 3 | 14 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-MOD-JOHNSON | shell-computus-gemini (gemini-2.5-pro) | True | — | 22 | 49 | FAIL | — |
| BM-MOD-JOHNSON | shell-r2-gemini (gemini-2.5-pro) | True | — | 21 | 49 | FAIL | — |
| BM-MOD-JOHNSON | shell-r5-gemini (gemini-2.5-pro) | True | — | 19 | 46 | FAIL | — |
| BM-MOD-DEED | shell-computus-gemini (gemini-2.5-pro) | True | — | 5 | 2 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-MOD-DEED | shell-full-computus-gemini (gemini-2.5-pro) | True | — | 5 | 3 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-MOD-DEED | shell-r2-gemini (gemini-2.5-pro) | True | — | 8 | 5 | FAIL | Warnings: suspected overconfidence (soft escalation §7.3–§7.4): multiline body text, conditionNotes suggest damage/abbre |
| BM-MOD-DEED | shell-r5-gemini (gemini-2.5-pro) | True | — | 7 | 6 | FAIL | — |
