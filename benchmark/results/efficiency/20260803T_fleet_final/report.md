# Pipeline efficiency report (multi-machine)

_Same pipeline everywhere; Settings differ by host (`--auto-efficiency`)._

## HTR page timing (same NYPL fixture, skip-gm)

| Host | GPU | HTR s | wall s |
|---|---|---:|---:|
| akdeniz | RTX 4090 | 9.268 | 9.271 |
| bridges_gpu | Tesla V100-SXM2-32GB | 132.462 | 132.626 |

_Bridges V100 ≈ **14.3×** slower than akdeniz 4090 on this page._

## Auto-efficiency Settings (identical stages)

- Shared: `lineation_backend=kraken`, `htr_combination=kraken_htr`, `llm_mode=correct`, `reuse_lines_xml=true`
- Differs: `batch_parallel_pages` (3 on 4090 if load OK; **1** on V100 / Mac / login)

## Where to run the same pipeline

| Use case | Preferred host |
|---|---|
| Interactive | **akdeniz** (4090) |
| Batch / train | **bridges_gpu** GPU-shared (`gpu:1`, qos=gpuinteract for short jobs) |
| Orchestrate + Gemini | **local Mac** |
| bridges_login | submit only — no GPU |

## ROI

- Cache `model_registry.load_all` / `by_name`
- Cache Kraken HTR `.mlmodel` across pages
- Prefer akdeniz for interactive HTR (~9s vs ~132s V100 on this page)
- Use `--auto-efficiency` so knobs follow the host without changing stages

Bridges job `42948067` COMPLETED; artifact `20260803T150344Z_bridges_gpu/`.
