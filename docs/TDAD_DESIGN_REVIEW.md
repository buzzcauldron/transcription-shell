# TDAD design review (structure and holes)

This document is the deliverable for the TDAD-based structure review. It references the blueprint under [`.tdad/workflows/`](../.tdad/workflows/) and the implementation under [`src/transcriber_shell/`](../src/transcriber_shell/).

Use the sections below as dropdowns to expand each part of the review.

<details>
<summary><strong>1. Modeling (TDAD graph vs code)</strong></summary>

### What the graph captures well

- **Glyph Machina** ([`glyph-machina.workflow.json`](../.tdad/workflows/glyph-machina/glyph-machina.workflow.json)) matches the step sequence in [`glyph_machina/workflow.py`](../src/transcriber_shell/glyph_machina/workflow.py): upload → crop → Identify Lines → download.
- **XML → LLM chain** links `save-downloaded-lines-xml` → `validate-lines-xml-textline-rules` → LLM nodes, matching the order in [`pipeline/run.py`](../src/transcriber_shell/pipeline/run.py) when Glyph Machina is used.
- **LLM stages** separate prompt composition, provider call, persistence, and schema validation, aligned with `run_transcribe`, `strip_yaml_fence`, file write, and `validate_transcript_file` in `run.py`.

### Gaps and mismatches

1. **No dedicated node for `run_pipeline` itself.** Orchestration is implicit in the cross-folder dependency chain. The central function [`run_pipeline()`](../src/transcriber_shell/pipeline/run.py) is the single place that encodes branching (`skip_gm`, `lines_xml_path`, `xsd_path`) and error aggregation; the TDAD graph shows linear feature dependencies instead of one “orchestrator” feature. *Impact:* the blueprint under-represents control flow and early exit on error.

2. **`skip_gm` is not a first-class branch.** When `skip_gm` is true, `validate-lines-xml-textline-rules` still lists `save-downloaded-lines-xml` as a dependency, but the real predecessor is user-supplied lines XML, not Glyph Machina. *Impact:* the DAG is accurate for the default path only; offline/batch workflows need mental mapping to [`resolve_lines_xml_for_image()`](../src/transcriber_shell/pipeline/batch.py).

3. **CLI is not modeled.** Commands in [`cli.py`](../src/transcriber_shell/cli.py) (`validate-xml`, `validate-yaml`, `run`, batch) are thin wrappers around the same modules; the graph has no `cli` folder. *Impact:* acceptable for TDAD (infrastructure/entrypoints are often out of scope), but CLI/API parity differences are easy to miss (see below).

4. **Optional XSD validation** is chained after TextLine validation in the graph; in code, XSD failures append errors but the pipeline structure is the same. The graph is fine; the nuance is that XSD is optional via `xsd_path`, not an unconditional step.

</details>

<details>
<summary><strong>2. Modularity and coupling</strong></summary>

1. **Import DAG (Python) is acyclic.** Packages follow `pipeline` → `glyph_machina` | `xml_tools` | `llm` → `config` | `models` | `protocol_paths`; `api` → `pipeline.run`. Nothing in `glyph_machina` or `llm` imports `pipeline`. No circular import was observed when importing with `PYTHONPATH=src`.

2. **Runtime coupling to vendored protocol.** [`protocol_paths.ensure_protocol_benchmark_on_path()`](../src/transcriber_shell/protocol_paths.py) mutates `sys.path` and is required for `prompt_builder` and `validate_schema`. This is a **single integration seam** with high blast radius if the submodule layout changes.

3. **API vs CLI behavior split.** [`api/app.py`](../src/transcriber_shell/api/app.py) rejects `skip_gm` on HTTP (`422`); CLI and batch support `skip_gm` with `--lines-xml` / `--lines-xml-dir`. The graph’s `/v1/transcribe` node does not encode that restriction—*design hole:* duplicated policy between API and CLI, risk of drift.

4. **FastAPI workarounds** (comment in `app.py`: `from __future__ import annotations` omitted; middleware instead of `Depends` for API key) indicate **tight coupling to framework/OpenAPI quirks**, not a domain issue, but they complicate refactors of auth.

</details>

<details>
<summary><strong>3. Test strategy (pytest vs TDAD / Playwright)</strong></summary>

| Area | Automated tests | TDAD `testLayers` in graph |
|------|-----------------|---------------------------|
| Glyph Machina UI | No tests in `tests/` (live site + Playwright) | `ui` |
| XML tools | [`tests/test_xml_tools.py`](../tests/test_xml_tools.py) | `api` (file-level validation) |
| Batch | [`tests/test_batch.py`](../tests/test_batch.py): discovery, `sanitize_job_id`, `resolve_lines_xml_for_image` | `api` |
| HTTP API | [`tests/test_api.py`](../tests/test_api.py): `/health`, Bearer auth on `/v1/transcribe`, `skip_gm` validation, multipart errors, mocked `run_pipeline` success | `api` |
| Pipeline | [`tests/test_pipeline_integration.py`](../tests/test_pipeline_integration.py): `run_pipeline` with `skip_gm` and mocked LLM/schema | `api` |
| Config | [`tests/test_config.py`](../tests/test_config.py) | — |

**Design holes:**

1. **TDAD Playwright traces not wired for this repo.** Glyph Machina nodes are genuinely UI-driven; absence of `.tdad/workflows/**` Playwright specs means the blueprint is **documentation-first** for that surface, not execution-linked.

2. **E2E API coverage** still uses mocks for `run_pipeline`; real multipart → full pipeline is not exercised in CI (would require API keys and/or Glyph Machina).

3. **Batch `run_batch` sequential loop** is not covered by an integration test (only unit tests for helpers).

</details>

<details>
<summary><strong>4. Operational and external risks</strong></summary>

1. **Submodule required** for LLM + `validate-yaml` paths: documented in README; [`protocol_paths.py`](../src/transcriber_shell/protocol_paths.py) raises `FileNotFoundError` with a clear message. Failure mode is explicit and centralized.

2. **External UI dependency:** Glyph Machina selectors and copy in [`docs/glyph-machina-automation.md`](../docs/glyph-machina-automation.md) note site drift—structural risk is **brittle E2E**, not internal module boundaries.

3. **Artifacts directory** and job IDs are shared across CLI, API, and GM; no separate “storage” node in TDAD—acceptable for a small tool, but concurrency or cleanup policies are not modeled.

</details>

<details>
<summary><strong>5. Node index (quick reference)</strong></summary>

| Workflow file | Feature node IDs (summary) |
|---------------|----------------------------|
| [`glyph-machina.workflow.json`](../.tdad/workflows/glyph-machina/glyph-machina.workflow.json) | `upload-pre-cropped-page-image` → `confirm-crop-image-action` → `run-identify-lines-step` → `save-downloaded-lines-xml` |
| [`xml-tools.workflow.json`](../.tdad/workflows/xml-tools/xml-tools.workflow.json) | `validate-lines-xml-textline-rules` → `validate-lines-xml-with-optional-xsd` |
| [`llm.workflow.json`](../.tdad/workflows/llm/llm.workflow.json) | `compose-protocol-prompt-zones` → `transcribe-image-with-llm-provider` → `persist-transcription-yaml-artifact` → `validate-transcript-file-protocol-schema` |
| [`pipeline.workflow.json`](../.tdad/workflows/pipeline/pipeline.workflow.json) | `discover-batch-images-from-path` → `run-sequential-batch-transcribe` |
| [`api.workflow.json`](../.tdad/workflows/api/api.workflow.json) | `authorize-v1-with-bearer-middleware`, `post-v1-transcribe-multipart`, `get-health-status` |

</details>

<details>
<summary><strong>6. Suggested follow-ups (optional)</strong></summary>

1. Add a **folder or feature node** for “orchestrate single job (`run_pipeline`)” if you want the blueprint to mirror the real control-flow hub, with notes on `skip_gm` in the description.
2. Add **pytest** (or TDAD API tests) for `POST /v1/transcribe` and Bearer middleware to match [`api.workflow.json`](../.tdad/workflows/api/api.workflow.json).
3. Add **Playwright** specs under `.tdad/workflows/glyph-machina/` when you want TDAD traces for Glyph Machina, accepting flakiness from third-party UI changes.

</details>

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.

