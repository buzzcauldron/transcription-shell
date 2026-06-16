# HTR model goals

A staged target for the locally trained Kraken HTR model
(`son-of-gm-*`), with explicit metrics, the held-out eval that proves
each stage, and what we earn at each milestone.

## North star

A locally trained, locally inferred Kraken HTR model that produces
**expanded Latin** directly from AALT-style English court manuscript
images — so the LLM stage can drop out or move to a tiny "fix what's
wrong" correction prompt, instead of full re-transcription.

GM's published model (`best_HTR.net`) tops at **CER 4.9%, WER 15.5%**
against **abbreviated (ink) GT** — same architecture, different output
target. Our specialization is that we score against
**expanded Latin GT**, which is what historians actually read.

## Phases

Each phase has a single number that has to land before we move on.
Metrics are computed by [run_eval3.py](../excomm-eval/run_eval3.py)
against a permanently held-out subset of the AALT pages
(no peeking — see *Eval discipline* below).

### Phase 0 — Baseline (today)

What the current model can do, measured honestly.

| Metric | `son-of-gm-r2-ep38` |
|---|---|
| Expanded-CER (held-out) | **81.69%** |
| Ink-CER (held-out) | **83.86%** |
| Expanded-WER | 99.57% |

**Status:** measured. The model is essentially blind to AALT court hand.
This is the baseline; everything below must beat it on the same set.

### Phase 1 — *In-domain readable* (target: weeks)

> **CER (ink) < 30%** on the held-out eval set.

What it earns: the LLM correction step starts to add value. At >50% CER
the LLM has too much to fix to be reliable; at <30% it's a
"clean-up this draft" job and Claude/GPT-4 can do it cheaply.

Levers required for this phase:
- ✅ Add 119 Excommunication AALT lines to r3 training (done)
- ✅ Add 196 Non-diplomatic AALT lines to r3 training (just produced)
- ⏳ r3 to converge on augmented manifest

### Phase 2 — *LLM-correct usable* (target: 1-2 months)

> **CER (ink) < 15%, WER (ink) < 50%** on held-out.

What it earns: `llm_mode=correct` becomes the primary pipeline.
LLM gets a draft that needs ~1 in 7 chars fixed, not ~1 in 3 — token
cost drops 5-10× vs full transcription.

Levers required:
- KenLM bigram decoder (corpus already built: 2,270 lines; needs `lmplz`
  install + pyctcdecode integration in `kraken_htr.py`)
- More in-domain training data: complete the docx alignment pipeline
  for the 27 currently-failing pairs (~700 more lines)
- r4 round trained from r3's converged best

### Phase 3 — *GM-parity ink HTR* (target: 3-6 months)

> **CER (ink) < 5%, WER (ink) < 16%** — i.e. match GM's published.

What it earns: confidence that our architecture + data pipeline is
right. After this we know any remaining gap on **expanded GT** is just
the expansion task, not a recognition deficit.

Levers required:
- TRIDIS Latin pretraining round (the move GM made from CER 6 → 5)
- Targeted hard-negative mining: re-run eval, find worst lines, hand-fix
  a few, retrain
- May need to switch to GM's exact architecture (TrOCR or their seq2seq)
  rather than stock Kraken

### Phase 4 — *Expanded HTR* (the differentiator; 6-12 months)

> **CER (expanded) < 10%** on held-out.

What it earns: the model directly produces what a historian reads. LLM
stage drops to optional. This is the publishable result.

Levers required:
- Training corpus must be **expanded** GT (we now have 2,270 lines; need
  10K+). Path: complete docx alignment, plus expand a chunk of the
  existing GM training set in-place.
- Loss-weighted training: confidence-weight abbreviation positions
  higher during training so the model learns to *write* the expansion
  even when the ink shows a tilde.
- Probably a final LLM correction layer remains for the long tail,
  but it does cleanup, not transcription.

## Eval discipline

The Excommunication folder has **6 PageXML files** with manual,
human-checked transcriptions. To avoid Goodharting:

- **Currently held out:** the **whole** 119-line Excommunication set.
  This is what [run_eval3.py](../excomm-eval/run_eval3.py) scores.
- **Hard rule:** these 6 pages **never** go into a training manifest.
  We currently added them to r3 — **revert this** before any
  meaningful Phase 1 measurement; otherwise the number is leaked.
- Replace the lost training signal by adding the 196 Non-diplomatic
  lines (different documents, similar hand).
- As more docx pairs come in, hold out 1 page per source category as
  permanent eval.

## What today's session changed

Concrete artifacts produced or staged this round:

| What | Where | Status |
|---|---|---|
| 119 Excommunication line pairs | [/home/sethj/excomm-eval/lines/](../excomm-eval/lines/) | **In r3 training (leak risk — see above)** |
| 196 Non-diplomatic line pairs | [/home/sethj/excomm-eval/non-diplomatic-train/](../excomm-eval/non-diplomatic-train/) | Ready to ship to server |
| Otsu projection seg | [projection_seg.py](../excomm-eval/projection_seg.py) | Working; 12/33 dense pages still fail (need peak detection) |
| 2,270-line Latin corpus | [corpus.expanded.txt](../excomm-eval/corpus.expanded.txt) | Ready for KenLM build (Phase 2) |
| Approximate abbreviator | [abbreviate.py](../excomm-eval/abbreviate.py) | Used to compute ink-CER vs expanded-CER |
| Dual-CER eval runner | [run_eval3.py](../excomm-eval/run_eval3.py) | Use this to measure every future model |

## Decisions outstanding

1. **Revert the leak?** Take the 119 Excommunication lines out of r3's
   training manifest? (Cost: ~0.4% of training signal. Benefit: a
   trustworthy eval signal from day one.)
2. **Build out the dense-text seg?** Peak detection on the row
   profile would recover the 27 currently-failing docx pages
   (estimated +700 lines).
3. **When do we install KenLM?** Phase 2 needs it. Probably worth doing
   alongside the next training round so r4 evaluation can use it.

Approve any of these and I'll execute.
