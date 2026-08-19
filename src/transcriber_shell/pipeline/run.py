"""Orchestrate: lineation → (optional HTR) → LLM → YAML normalize/validate."""

from __future__ import annotations

import errno
import json
import time
from datetime import datetime, timezone
from typing import Any
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import re

import httpx
import yaml

from transcriber_shell.config import LineationBackend, Settings
from transcriber_shell.glyph_machina.workflow import GlyphMachinaError, fetch_lines_xml
from transcriber_shell.kraken_lineation import KrakenLineationError, fetch_lines_xml_kraken
from transcriber_shell.llm.errors import (
    LLMProviderError,
    is_llm_cap_error,
    llm_cap_tripped,
    trip_llm_cap,
)
from transcriber_shell.mask_lineation import MaskLineationError, fetch_lines_xml_mask
from transcriber_shell.llm.transcribe import run_transcribe, strip_yaml_fence, TranscribeResult
from transcriber_shell.llm.validate_output import (
    has_correct_mode_text,
    is_htr_only_transcript,
    normalize_transcription_yaml_data,
    validate_transcript_file,
)
from transcriber_shell.models.job import PipelineResult, TranscribeJob
from transcriber_shell.pipeline.transcription_paths import (
    lines_xml_canonical_path,
    transcription_txt_path,
    transcription_yaml_path,
)
from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional


_UNCERTAIN_PLACEHOLDER = "UNCERTAIN_COLON"
_UNCERTAIN_TOKEN_RE = re.compile(r"\[uncertain:")


def _repair_yaml_uncertain_tokens(raw: str) -> str:
    """Pre-process raw YAML to survive [uncertain: X / Y] tokens.

    The ': ' inside [uncertain: ...] brackets confuses the YAML parser when
    the value is an unquoted plain scalar (YAML reads 'uncertain' as a key).
    Strategy:
      1. Replace '[uncertain:' with a placeholder that contains no YAML
         special characters.
      2. Parse with yaml.safe_load (caller's responsibility).
      3. Caller must call _restore_uncertain_tokens() on the parsed dict
         before writing back, or call yaml.safe_dump which quotes strings.
    Note: the placeholder must be restored; see _restore_uncertain_in_dict().
    """
    return _UNCERTAIN_TOKEN_RE.sub(_UNCERTAIN_PLACEHOLDER, raw)


def _restore_uncertain_in_dict(obj: Any) -> Any:
    """Walk a parsed YAML structure and restore [uncertain: placeholders."""
    if isinstance(obj, str):
        return obj.replace(_UNCERTAIN_PLACEHOLDER, "[uncertain:")
    if isinstance(obj, dict):
        return {k: _restore_uncertain_in_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_restore_uncertain_in_dict(v) for v in obj]
    return obj


def _extract_plain_text(data: dict) -> str:
    """Extract segment text from a normalized transcription YAML dict."""
    root = data.get("transcriptionOutput", data)
    if not isinstance(root, dict):
        return ""
    segs = root.get("segments") or []
    texts = [
        seg["text"].strip()
        for seg in segs
        if isinstance(seg, dict) and isinstance(seg.get("text"), str) and seg["text"].strip()
    ]
    return "\n\n".join(texts)


def _approximate_text_line_count(lines_xml: Path) -> int:
    """Best-effort TextLine count when full validation is skipped."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(str(lines_xml)).getroot()
        count = sum(
            1 for el in root.iter()
            if (el.tag.split("}")[-1] if "}" in el.tag else el.tag) == "TextLine"
        )
        return count
    except Exception:
        pass
    try:
        text = lines_xml.read_text(encoding="utf-8", errors="replace")
        return max(text.count("<TextLine"), text.count(":TextLine"))
    except OSError:
        return 0


def _llm_network_timeout_hint(job: TranscribeJob) -> str:
    """User-facing text for HTTP/socket timeouts during run_transcribe (not API-key hints)."""
    prov = job.provider.lower()
    parts = [
        "This is a network-level timeout while calling the LLM, not necessarily a bad API key.",
        "If the run log already showed lines_xml=, lineation finished and this failure is during the LLM step.",
    ]
    if prov == "anthropic":
        parts.append(
            "For Anthropic, try increasing TRANSCRIBER_SHELL_ANTHROPIC_TIMEOUT_S (default 600s)."
        )
    if prov == "ollama":
        parts.append(
            "For Ollama, try increasing TRANSCRIBER_SHELL_OLLAMA_TIMEOUT_S (default 3600s); "
            "local vision models are often slow on CPU."
        )
    parts.append(
        "If you use a proxy, set TRANSCRIBER_SHELL_LLM_USE_PROXY and/or "
        "TRANSCRIBER_SHELL_LLM_HTTP_PROXY when appropriate."
    )
    return " ".join(parts)


def _htr_results_to_line_hint(htr_results: dict[str, Any]) -> str | None:
    """Turn HTR backend output into an optional LLM hint (truncated)."""
    from transcriber_shell.htr.base import HtrResult

    # ONE DRAFT, NOT ALL OF THEM.
    #
    # Every backend's draft used to go into the prompt at cap=6000 chars each, so
    # running Glyph Machina AND Kraken doubled the draft payload to ~3,000 input
    # tokens per page before anything else. Correct mode needs the BEST draft, not
    # a chorus: the model is being asked to fix recognition errors, and a second
    # noisy draft adds tokens without adding information it can act on.
    #
    # Ranked by confidence when the backend reports one, else by line count as a
    # proxy for coverage. Failures are still surfaced so a silently dead backend
    # does not look like a clean run.
    _CONF_RANK = {"high": 3, "medium": 2, "low": 1}

    def _score(r: object) -> tuple[int, int]:
        if not isinstance(r, HtrResult):
            return (-1, -1)
        return (_CONF_RANK.get(str(r.confidence or "").lower(), 0), int(r.line_count or 0))

    usable = {n: r for n, r in htr_results.items()
              if isinstance(r, HtrResult) and r.text.strip()}
    if len(usable) > 1:
        best = max(usable, key=lambda n: _score(usable[n]))
        htr_results = {best: usable[best],
                       **{n: r for n, r in htr_results.items() if isinstance(r, Exception)}}

    parts: list[str] = []
    for name, res in htr_results.items():
        if isinstance(res, Exception):
            parts.append(f"{name}: HTR failed ({res}).")
            continue
        if isinstance(res, HtrResult) and res.text.strip():
            cap = 6000
            body = res.text.strip()
            if len(body) > cap:
                body = body[:cap] + "\n[... truncated from HTR draft ...]"
            tier = res.confidence or "n/a"
            parts.append(
                f"--- {name} (machine draft, {res.line_count} lines, tier={tier}) ---\n{body}"
            )
    if not parts:
        return None
    return (
        "HTR machine-readable drafts (for cross-check only; output must still be full protocol YAML):\n"
        + "\n".join(parts)
    )


def _has_usable_htr_draft(htr_results: dict[str, Any] | None) -> bool:
    """True when at least one HTR backend returned non-empty text."""
    from transcriber_shell.htr.base import HtrResult

    if not htr_results:
        return False
    for res in htr_results.values():
        if isinstance(res, HtrResult) and res.text.strip():
            return True
    return False


def _refuse_llm_without_htr(
    job: TranscribeJob,
    s: Settings,
    *,
    lines_out: Path | None,
    text_line_count: int,
    htr_results: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    timings: list[tuple[str, float]],
    reason: str,
) -> PipelineResult:
    errors.append(
        f"HTR→LLM required: refusing LLM without a usable HTR draft ({reason}). "
        "Configure a Kraken/GM/TrOCR model (htr_combination=kraken_htr|gm_htr|…), "
        "or set TRANSCRIBER_SHELL_REQUIRE_HTR_BEFORE_LLM=0 only for deliberate LLM-only experiments."
    )
    return PipelineResult(
        job.job_id,
        lines_out,
        None,
        text_line_count,
        errors=errors,
        warnings=warnings,
        htr_results=dict(htr_results or {}),
        timings=timings,
    )


def _collect_htr_parallel(
    htr_future: Future | None,
    htr_executor: ThreadPoolExecutor | None,
    warnings: list[str],
) -> dict[str, Any]:
    htr_results: dict[str, Any] = {}
    if htr_future is not None:
        try:
            htr_results = htr_future.result(timeout=300)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"HTR parallel runner error: {exc}")
        finally:
            if htr_executor is not None:
                htr_executor.shutdown(wait=False)
    return htr_results


def _finalize_htr_results(
    htr_results_early: dict[str, Any],
    htr_future: Future | None,
    htr_executor: ThreadPoolExecutor | None,
    warnings: list[str],
) -> dict[str, Any]:
    """Prefer sequential HTR results; otherwise drain the parallel HTR future."""
    if htr_results_early:
        return dict(htr_results_early)
    return _collect_htr_parallel(htr_future, htr_executor, warnings)


def _fixup_protocol_compliance(data: dict[str, Any]) -> None:
    """Patch common LLM protocol violations in-place before validation.

    §5.2: mismatchReport:[] with no pass2Summary is invalid — add the shorthand stub.
    §5.6: uncertainty flooding without conditionNotes — inject a script-based note.
    """
    root = data.get("transcriptionOutput")
    if not isinstance(root, dict):
        return

    segs = root.get("segments")
    if not isinstance(segs, list) or not segs:
        return

    # §5.2 fix: empty mismatchReport with no pass2Summary
    mr = root.get("mismatchReport")
    p2s = root.get("pass2Summary")
    if isinstance(mr, list) and len(mr) == 0 and not p2s:
        root["pass2Summary"] = {"passCount": 2, "segmentsAltered": 0}

    # §5.6 fix: add conditionNotes when uncertainty would flood without documentation
    pre = root.get("preCheck")
    if not isinstance(pre, dict):
        return
    cn = pre.get("conditionNotes")
    has_notes = isinstance(cn, str) and len(cn.strip()) >= 20
    if has_notes:
        return
    full_text = " ".join(str(s.get("text", "")) for s in segs if isinstance(s, dict))
    import re as _re
    n_unc = len(_re.findall(r"\[uncertain:", full_text, _re.IGNORECASE))
    n_words = len(_re.findall(r"\S+", _re.sub(r"\[uncertain:[^\]]*\]", " µ ", full_text)))
    if n_words > 0 and n_unc / n_words > 0.30:
        script = pre.get("scriptIdentified") or "the script"
        pre["conditionNotes"] = (
            f"High abbreviation density and ambiguous letterforms in {script} "
            f"produce systematic reading uncertainty; conservative marking applied."
        )


def _format_llm_error(job: TranscribeJob, exc: BaseException) -> str:
    """One place that maps an LLM-call exception to a user-facing message."""
    prov = job.provider.lower()
    if isinstance(exc, LLMProviderError):
        hint = " See docs/claude_anthropic_reference.md for Anthropic-specific troubleshooting." if prov == "anthropic" else ""
        return f"LLM transcription failed ({job.provider}): {exc}{hint}"
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"LLM transcription failed ({job.provider}): {exc} ({type(exc).__name__}). "
            f"{_llm_network_timeout_hint(job)}"
        )
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ETIMEDOUT
    ):
        return f"LLM transcription failed ({job.provider}): {exc}. {_llm_network_timeout_hint(job)}"
    return (
        f"LLM transcription failed ({job.provider}): {exc}. "
        "Check API key in .env or the GUI, provider outage/rate limits, and that the model id is valid."
    )


def _htr_only_short_circuit(
    job: TranscribeJob,
    s: Settings,
    lines_out: Path | None,
    text_line_count: int,
    htr_results: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    timings: list[tuple[str, float]],
    *,
    mark_needs_llm: bool = True,
) -> PipelineResult:
    """Write on-machine Kraken HTR as YAML and skip the LLM step."""
    from transcriber_shell.htr.base import HtrResult as _HtrResult

    lines: list[str] = []
    backend = "kraken-htr"
    for res in htr_results.values():
        if not isinstance(res, _HtrResult) or not res.text.strip():
            continue
        backend = res.backend or backend
        lines.extend(ln.strip() for ln in res.text.splitlines() if ln.strip())
    if not lines:
        errors.append("htr_only: HTR returned no text.")
        return PipelineResult(
            job.job_id, lines_out, None, text_line_count,
            errors=errors, warnings=warnings, htr_results=htr_results, timings=timings,
        )
    raw_htr = "\n".join(lines)
    payload = {
        "transcriptionOutput": {
            "metadata": {
                "modelId": backend,
                "notes": "htr_only: on-machine Kraken; not protocol-compliant (no LLM correct)",
            },
            "segments": [{"text": ln, "position": "main"} for ln in lines],
        }
    }
    out_yaml = transcription_yaml_path(s.artifacts_dir, job.job_id, job.image_path)
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        out_yaml.with_suffix(".txt").write_text(raw_htr + "\n", encoding="utf-8")
    except OSError:
        pass
    if (s.llm_mode or "full").strip().lower() != "off" and mark_needs_llm:
        try:
            (out_yaml.parent / ".needs_llm").write_text(
                "htr_only: LLM cleanup not applied\n", encoding="utf-8"
            )
        except OSError:
            pass
    warnings.append("htr_only: on-machine HTR YAML (no LLM correct).")
    expanded_tei: Path | None = None
    expanded_txt: Path | None = None
    if s.expand_diplomatic_enabled:
        from transcriber_shell.expand.bridge import maybe_run_expand_stage

        s_rules = s.model_copy(
            update={
                "expand_diplomatic_backend": "rules",
                "expand_diplomatic_whole_document": False,
            }
        )
        t_exp = time.perf_counter()
        expanded_tei, expanded_txt, expand_warns = maybe_run_expand_stage(
            out_yaml, job.prompt_cfg, s_rules
        )
        warnings.extend(expand_warns)
        if expanded_tei is not None:
            timings.append(("expand", time.perf_counter() - t_exp))
    return PipelineResult(
        job.job_id, lines_out, out_yaml, text_line_count,
        errors=errors, warnings=warnings, htr_results=htr_results, timings=timings,
        expanded_tei_path=expanded_tei,
        expanded_txt_path=expanded_txt,
    )


def _best_htr_draft(htr_results: dict[str, Any]) -> str | None:
    """Raw text of the highest-confidence HTR draft, or None."""
    from transcriber_shell.htr.base import HtrResult

    best, best_score = None, (-1, -1)
    rank = {"high": 3, "medium": 2, "low": 1}
    for res in (htr_results or {}).values():
        if not isinstance(res, HtrResult) or not res.text.strip():
            continue
        score = (rank.get(str(res.confidence or "").lower(), 0), int(res.line_count or 0))
        if score > best_score:
            best, best_score = res.text.strip(), score
    return best


def _append_htr_hint(job: TranscribeJob, htr_results: dict[str, Any]) -> None:
    """Append HTR drafts to ``job.line_hint`` when results are available."""
    hint_extra = _htr_results_to_line_hint(htr_results)
    if hint_extra:
        job.line_hint = f"{job.line_hint}\n\n{hint_extra}" if job.line_hint else hint_extra
    # Kept separately and untruncated for diff-based correction.
    job.htr_draft_raw = _best_htr_draft(htr_results)


def _htr_results_from_yaml(path: Path) -> dict[str, Any]:
    """Rebuild HTR drafts from an existing ``htr_only`` YAML so Kraken is not re-run."""
    from transcriber_shell.htr.base import HtrResult
    from transcriber_shell.llm.validate_output import load_transcription_root, load_yaml_or_json_path

    try:
        data = load_yaml_or_json_path(path)
        root = load_transcription_root(data) or {}
    except Exception:
        return {}
    lines: list[str] = []
    for seg in root.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or seg.get("diplomaticText") or "").strip()
        if text:
            lines.append(text)
    if not lines:
        return {}
    joined = "\n".join(lines)
    return {
        "cached-htr": HtrResult(
            text=joined,
            backend="cached-htr",
            line_count=len(lines),
        )
    }


def _clear_needs_llm_marker(out_yaml: Path) -> None:
    marker = out_yaml.parent / ".needs_llm"
    try:
        if marker.is_file():
            marker.unlink()
    except OSError:
        pass


def _do_htr(
    job: TranscribeJob,
    s: Settings,
    lines_out: Path,
    errors: list[str],
    warnings: list[str],
    timings: list[tuple[str, float]],
    text_line_count: int,
    _log,
) -> tuple[dict[str, Any], Future | None, ThreadPoolExecutor | None, PipelineResult | None]:
    """Plan and run HTR backends per ``htr_combination``.

    Returns ``(early_results, future, executor, short_circuit)``.
    ``short_circuit`` is a complete ``PipelineResult`` only when the plan is ``HTR_ONLY``
    (or HTR errored under that plan) — the caller must return it immediately and skip the LLM.
    """
    existing = transcription_yaml_path(s.artifacts_dir, job.job_id, job.image_path)
    if (
        (s.llm_mode or "full").strip().lower() == "correct"
        and not llm_cap_tripped()
        and existing.is_file()
        and is_htr_only_transcript(existing)
    ):
        reused = _htr_results_from_yaml(existing)
        if _has_usable_htr_draft(reused):
            warnings.append("Reused on-machine HTR YAML for LLM autocorrect.")
            _log("htr: reused existing htr_only YAML (LLM autocorrect pass)")
            _append_htr_hint(job, reused)
            return reused, None, None, None

    from transcriber_shell.htr.detect import detect_scripts
    from transcriber_shell.htr.parallel import build_htr_tasks, run_htr_ordered, run_htr_parallel
    from transcriber_shell.htr.selector import HtrPlanKind, plan_htr_execution

    scripts = detect_scripts(job.prompt_cfg)
    htr_tasks = build_htr_tasks(job.image_path, lines_out, scripts, s)
    plan = plan_htr_execution(s, htr_tasks)

    early: dict[str, Any] = {}

    if plan.kind == HtrPlanKind.NONE:
        combo = (s.htr_combination or "").strip().lower()
        if combo in ("shell", "off", "none", "llm_only"):
            msg = (
                "HTR backends are configured (Glyph Machina and/or Zenodo paths) but "
                f"htr_combination={s.htr_combination!r} runs the original shell (LLM) only; HTR was skipped."
            )
            if getattr(s, "require_htr_before_llm", True) and (s.llm_mode or "full").lower() != "off":
                errors.append(msg + " LLM blocked (require_htr_before_llm).")
            elif htr_tasks:
                warnings.append(msg)
        elif getattr(s, "require_htr_before_llm", True) and (s.llm_mode or "full").lower() != "off":
            errors.append(
                "HTR→LLM required: no HTR backend tasks available for "
                f"htr_combination={s.htr_combination!r}. Configure model paths or change combination."
            )
        return early, None, None, None

    if plan.kind == HtrPlanKind.WITH_LLM_PARALLEL and plan.tasks:
        # Parallel-with-LLM is only reachable when require_htr_before_llm is false.
        _log("htr: starting (parallel with LLM)…")
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_htr_parallel, plan.tasks)
        return early, future, executor, None

    label = "htr_only — LLM skipped" if plan.kind == HtrPlanKind.HTR_ONLY else "before LLM"
    _log(f"htr: starting ({label})…")
    t0 = time.perf_counter()
    try:
        if plan.kind == HtrPlanKind.BEFORE_LLM_ORDERED and plan.ordered:
            early = run_htr_ordered(plan.ordered)
        elif plan.tasks:
            early = run_htr_parallel(plan.tasks)
    except Exception as exc:  # noqa: BLE001
        if plan.kind == HtrPlanKind.HTR_ONLY:
            errors.append(f"HTR runner error: {exc}")
            return early, None, None, PipelineResult(
                job.job_id, lines_out, None, text_line_count,
                errors=errors, warnings=warnings, timings=timings,
            )
        kind = "ordered " if plan.kind == HtrPlanKind.BEFORE_LLM_ORDERED else ""
        warnings.append(f"HTR {kind}runner error: {exc}")
        early = {}
    timings.append(("htr", time.perf_counter() - t0))
    _log(f"htr: done ({timings[-1][1]:.1f}s)")

    if plan.kind == HtrPlanKind.HTR_ONLY:
        return early, None, None, _htr_only_short_circuit(
            job, s, lines_out, text_line_count, early, errors, warnings, timings,
        )

    _append_htr_hint(job, early)
    return early, None, None, None



def run_pipeline(
    job: TranscribeJob,
    *,
    skip_gm: bool = False,
    lines_xml_path: Path | None = None,
    xsd_path: Path | None = None,
    require_text_line: bool = True,
    skip_lines_xml_validation: bool | None = None,
    settings: Settings | None = None,
    lineation_backend: LineationBackend | None = None,
    log_fn=None,
) -> PipelineResult:
    def _log(msg: str) -> None:
        if log_fn is not None:
            log_fn(msg)
    s = settings or Settings()
    if lineation_backend is not None:
        s = s.model_copy(update={"lineation_backend": lineation_backend})
    skip_xml = (
        s.skip_lines_xml_validation
        if skip_lines_xml_validation is None
        else skip_lines_xml_validation
    )
    errors: list[str] = []
    warnings: list[str] = []
    timings: list[tuple[str, float]] = []

    lines_out: Path | None = None
    text_line_count = 0

    _t = time.perf_counter()
    if skip_gm:
        _log("lineation: skipped (using existing lines XML)")
        if not lines_xml_path or not lines_xml_path.is_file():
            p = lines_xml_path if lines_xml_path else "(not set)"
            errors.append(
                f"Skip Glyph Machina requires an existing lines XML file. Got: {p}. "
                "Use --lines-xml (one image) or --lines-xml-dir with <stem>.xml per page (batch)."
            )
            return PipelineResult(
                job.job_id,
                None,
                None,
                0,
                errors=errors,
                warnings=warnings,
            )
        lines_out = lines_xml_path.resolve()
    elif (
        getattr(s, "reuse_lines_xml", True)
        and (canonical := lines_xml_canonical_path(s.artifacts_dir, job.job_id)).is_file()
        and canonical.stat().st_size > 0
    ):
        # Reuse an existing artifacts/<job_id>/lines.xml when present.
        # Saves the ~8 s/page lineation cost when retrying after an LLM failure.
        _log(f"lineation: reused {canonical} (cached from previous run)")
        lines_out = canonical
    else:
        backend = s.lineation_backend
        _log(f"lineation: starting ({backend})…")
        try:
            if backend == "mask":
                lines_out = fetch_lines_xml_mask(job.image_path, job.job_id, settings=s)
            elif backend == "kraken":
                lines_out = fetch_lines_xml_kraken(job.image_path, job.job_id, settings=s)
            else:
                lines_out = fetch_lines_xml(job.image_path, job.job_id, settings=s)
        except (MaskLineationError, KrakenLineationError, GlyphMachinaError) as e:
            if s.continue_on_lineation_failure:
                lines_out = None
                warnings.append(
                    f"Lineation failed ({s.lineation_backend}): {e}. "
                    "Continuing without lines XML (continue_on_lineation_failure). "
                    "Segment lineRange alignment may be weaker; supply manual lines XML or retry lineation."
                )
                if not job.line_hint:
                    job.line_hint = (
                        "Lineation step failed or unavailable; infer layout from the page image only."
                    )
            else:
                errors.append(str(e))
                return PipelineResult(
                    job.job_id,
                    None,
                    None,
                    0,
                    errors=errors,
                    warnings=warnings,
                )
        except (TimeoutError, OSError) as e:
            if s.continue_on_lineation_failure:
                lines_out = None
                warnings.append(
                    f"Lineation failed ({s.lineation_backend}): network or OS timeout: {e}. "
                    "Continuing without lines XML (continue_on_lineation_failure). "
                    "Segment lineRange alignment may be weaker; supply manual lines XML or retry lineation."
                )
                if not job.line_hint:
                    job.line_hint = (
                        "Lineation step failed or unavailable; infer layout from the page image only."
                    )
            else:
                errors.append(
                    f"Lineation failed ({s.lineation_backend}): network or OS timeout: {e}. "
                    "Check connectivity or use Skip automated lineation with an existing lines XML file."
                )
                return PipelineResult(
                    job.job_id,
                    None,
                    None,
                    0,
                    errors=errors,
                    warnings=warnings,
                )

    _lineation_s = time.perf_counter() - _t
    timings.append(("lineation", _lineation_s))
    if not skip_gm:
        _log(f"lineation: done ({_lineation_s:.1f}s)")

    if lines_out is None and not skip_gm:
        # continue_on_lineation_failure path: no lines file to validate
        text_line_count = 0
    elif skip_xml:
        warnings.append(
            "Lines XML validation was skipped (well-formed XML, TextLine rules, and optional PAGE XSD were not enforced)."
        )
        text_line_count = _approximate_text_line_count(lines_out)
    else:
        ok, xml_msgs, stats = validate_lines_xml(
            str(lines_out), require_text_line=require_text_line
        )
        warnings.extend(m for m in xml_msgs if m.startswith("warning:"))
        errors.extend(m for m in xml_msgs if m.startswith("error:"))
        if not ok:
            errors.append(
                "Lines XML did not pass validation (well-formed XML, TextLine rules, or optional checks). "
                "See detailed messages above; try unchecking 'Require ≥1 TextLine' if your file has no TextLine yet, "
                "or use --skip-lines-xml-validation / TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION to bypass checks."
            )
        text_line_count = int(stats.get("text_line", 0))

        if xsd_path and lines_out:
            xsd_ok, xsd_errs = validate_xsd_optional(lines_out, xsd_path)
            if not xsd_ok:
                errors.extend(xsd_errs)

    if errors:
        return PipelineResult(
            job.job_id,
            lines_out,
            None,
            text_line_count,
            errors=errors,
            warnings=warnings,
        )

    if s.xml_only:
        if lines_out is None:
            errors.append(
                "XML-only mode requires a lines XML file (from lineation or skip lineation with an existing lines XML path)."
            )
            return PipelineResult(
                job.job_id,
                None,
                None,
                text_line_count,
                errors=errors,
                warnings=warnings,
            )
        warnings.append(
            "XML-only run: stopped after lines XML validation; LLM transcription was not performed."
        )
        return PipelineResult(
            job.job_id,
            lines_out,
            None,
            text_line_count,
            errors=[],
            warnings=warnings,
            llm_usage=None,
        )

    _MAX_SEGMENTS_PER_CALL = 80
    if not job.line_hint and text_line_count > 0:
        if text_line_count <= _MAX_SEGMENTS_PER_CALL:
            job.line_hint = (
                f"PageXML line detector reports {text_line_count} TextLine element(s); "
                "your segment count must match it exactly."
            )
        else:
            job.line_hint = (
                f"PageXML line detector reports {text_line_count} TextLine element(s). "
                f"This page is too dense for a single pass — transcribe the first "
                f"{_MAX_SEGMENTS_PER_CALL} TextLines only (lineRange 1–{_MAX_SEGMENTS_PER_CALL}); "
                "mark the final segment notes field with 'page_continues: true'."
            )

    # ── HTR ───────────────────────────────────────────────────────────────
    htr_future: Future | None = None
    htr_executor: ThreadPoolExecutor | None = None
    htr_results_early: dict[str, Any] = {}
    require_htr = bool(getattr(s, "require_htr_before_llm", True))
    llm_on = (s.llm_mode or "full").lower() != "off"

    if lines_out is not None and not s.xml_only:
        htr_results_early, htr_future, htr_executor, short_circuit = _do_htr(
            job, s, lines_out, errors, warnings, timings, text_line_count, _log,
        )
        if short_circuit is not None:
            return short_circuit
        if errors:
            return PipelineResult(
                job.job_id,
                lines_out,
                None,
                text_line_count,
                errors=errors,
                warnings=warnings,
                htr_results=dict(htr_results_early or {}),
                timings=timings,
            )
    elif require_htr and llm_on and not s.xml_only:
        return _refuse_llm_without_htr(
            job,
            s,
            lines_out=lines_out,
            text_line_count=text_line_count,
            htr_results={},
            errors=errors,
            warnings=warnings,
            timings=timings,
            reason="no lines XML — HTR cannot run (lineation failed or was skipped)",
        )

    # llm_mode=off short-circuits to the same htr_only output path when drafts exist.
    if (s.llm_mode or "full").lower() == "off" and htr_results_early:
        return _htr_only_short_circuit(
            job, s, lines_out, text_line_count, htr_results_early, errors, warnings, timings,
        )

    if require_htr and llm_on and not _has_usable_htr_draft(htr_results_early):
        # Drain a parallel future if somehow still pending (opt-out path only).
        if htr_future is not None:
            htr_results_early = _finalize_htr_results(
                htr_results_early, htr_future, htr_executor, warnings
            )
            _append_htr_hint(job, htr_results_early)
        if not _has_usable_htr_draft(htr_results_early):
            return _refuse_llm_without_htr(
                job,
                s,
                lines_out=lines_out,
                text_line_count=text_line_count,
                htr_results=htr_results_early,
                errors=errors,
                warnings=warnings,
                timings=timings,
                reason="HTR produced no non-empty draft text",
            )

    # ── LLM ───────────────────────────────────────────────────────────────
    if (s.llm_mode or "full").strip().lower() == "correct" and llm_cap_tripped():
        htr = _finalize_htr_results(htr_results_early, htr_future, htr_executor, warnings)
        warnings.append("LLM autocorrect skipped (rate limit / quota); kept on-machine HTR.")
        _log("llm: cap already hit — skipped autocorrect, kept Kraken HTR")
        return _htr_only_short_circuit(
            job, s, lines_out, text_line_count, htr, [], warnings, timings,
            mark_needs_llm=False,
        )

    _log(f"llm: starting ({job.provider}/{job.model_override or 'default'})…")
    llm_usage: dict[str, int] | None = None
    t_llm = time.perf_counter()
    try:
        tx = run_transcribe(job, settings=s)
    except (LLMProviderError, TimeoutError, OSError, httpx.TimeoutException, Exception) as e:
        htr = _finalize_htr_results(htr_results_early, htr_future, htr_executor, warnings)
        if _has_usable_htr_draft(htr):
            warnings.append(
                "LLM cleanup failed; kept on-machine HTR. " + _format_llm_error(job, e)
            )
            if is_llm_cap_error(e):
                trip_llm_cap()
                _log("llm: cap — kept Kraken HTR, skipping autocorrect on remaining pages")
            else:
                _log("llm: failed — saved Kraken HTR (cleanup deferred)")
            return _htr_only_short_circuit(
                job, s, lines_out, text_line_count, htr, [], warnings, timings,
                mark_needs_llm=not is_llm_cap_error(e),
            )
        errors.append(_format_llm_error(job, e))
        return PipelineResult(
            job.job_id, lines_out, None, text_line_count,
            errors=errors, warnings=warnings,
            htr_results=htr,
            timings=timings,
        )
    if isinstance(tx, TranscribeResult):
        raw, llm_usage = tx.text, tx.usage
    else:  # pragma: no cover — tests may mock with plain str
        raw = tx
    _llm_s = time.perf_counter() - t_llm
    timings.append(("llm", _llm_s))
    _log(f"llm: done ({_llm_s:.1f}s)")

    # DIFF-BASED CORRECTION: the response is a list of changed lines, not a page.
    # Merge it into the draft locally. Falls back to normal transcript handling if
    # the model ignored the format, so enabling the flag cannot blank a page.
    draft_lines = job.prompt_cfg.pop("_diff_draft_lines", None)
    if draft_lines:
        from transcriber_shell.llm.correct_diff import (
            apply_corrections,
            corrections_to_transcript,
            parse_corrections,
        )

        corrections = parse_corrections(raw)
        if corrections is None:
            warnings.append(
                "correct_mode_diff: model did not return a corrections document; "
                "treating the response as a full transcript instead."
            )
        else:
            merged, out_of_range = apply_corrections(draft_lines, corrections)
            if out_of_range:
                warnings.append(
                    "correct_mode_diff: ignored out-of-range line number(s) "
                    f"{out_of_range} — the model referenced lines the draft does not have."
                )
            _log(
                f"correct(diff): {len(corrections)} of {len(draft_lines)} lines changed"
            )
            model_id = job.model_override or s.resolved_model(job.provider)
            data = corrections_to_transcript(
                merged,
                normalization_mode=str(job.prompt_cfg.get("normalizationMode") or "diplomatic"),
                model_id=model_id,
            )
            meta = data["transcriptionOutput"]["metadata"]
            meta["timestamp"] = datetime.now(timezone.utc).isoformat()
            meta["correctionMode"] = "diff"
            meta["linesChanged"] = len(corrections)
            meta["linesTotal"] = len(draft_lines)
            out_yaml = transcription_yaml_path(s.artifacts_dir, job.job_id, job.image_path)
            out_yaml.parent.mkdir(parents=True, exist_ok=True)
            out_yaml.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            try:
                transcription_txt_path(
                    s.artifacts_dir, job.job_id, job.image_path
                ).write_text(_extract_plain_text(data), encoding="utf-8")
            except OSError:
                pass
            return PipelineResult(
                job.job_id, lines_out, out_yaml, text_line_count,
                errors=errors, warnings=warnings, llm_usage=llm_usage,
                htr_results=_finalize_htr_results(
                    htr_results_early, htr_future, htr_executor, warnings
                ),
                timings=timings,
            )

    raw = strip_yaml_fence(raw)
    raw = _repair_yaml_uncertain_tokens(raw)
    out_yaml = transcription_yaml_path(s.artifacts_dir, job.job_id, job.image_path)
    out_yaml.parent.mkdir(parents=True, exist_ok=True)

    normalized_data: dict | None = None
    try:
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            data = _restore_uncertain_in_dict(data)
            normalize_transcription_yaml_data(data)
            _fixup_protocol_compliance(data)
            _actual_model = job.model_override or s.resolved_model(job.provider)
            _meta = (data.get("transcriptionOutput") or {}).get("metadata")
            if isinstance(_meta, dict):
                _meta["modelId"] = _actual_model
                _meta["timestamp"] = datetime.now(timezone.utc).isoformat()
            out_yaml.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
            _clear_needs_llm_marker(out_yaml)
            out_txt = transcription_txt_path(s.artifacts_dir, job.job_id, job.image_path)
            try:
                out_txt.write_text(_extract_plain_text(data), encoding="utf-8")
            except OSError:
                pass
            normalized_data = data
        else:
            out_yaml.write_text(raw, encoding="utf-8")
    except yaml.YAMLError as e:
        out_yaml.write_text(raw, encoding="utf-8")
        errors.append(
            f"Model returned text that is not valid YAML: {e}. "
            "Retry or switch model; ensure the prompt asks for YAML matching the Academic Transcription Protocol."
        )
        return PipelineResult(
            job.job_id,
            lines_out,
            out_yaml,
            text_line_count,
            errors=errors,
            warnings=warnings,
            llm_usage=llm_usage,
            htr_results=_finalize_htr_results(
                htr_results_early, htr_future, htr_executor, warnings
            ),
        )

    val_ok, val_errs, val_warns = validate_transcript_file(
        out_yaml, settings=s, preloaded_data=normalized_data
    )
    warnings.extend(val_warns)
    if not val_ok:
        if has_correct_mode_text(out_yaml):
            warnings.extend(val_errs)
        else:
            errors.extend(val_errs)

    expanded_tei: Path | None = None
    expanded_txt: Path | None = None
    if val_ok and out_yaml is not None:
        from transcriber_shell.expand.bridge import maybe_run_expand_stage

        t_exp = time.perf_counter()
        expanded_tei, expanded_txt, expand_warns = maybe_run_expand_stage(
            out_yaml,
            job.prompt_cfg,
            s,
            log_fn=_log,
        )
        warnings.extend(expand_warns)
        if expanded_tei is not None:
            timings.append(("expand", time.perf_counter() - t_exp))

    return PipelineResult(
        job.job_id, lines_out, out_yaml, text_line_count,
        errors=errors, warnings=warnings, llm_usage=llm_usage,
        htr_results=_finalize_htr_results(htr_results_early, htr_future, htr_executor, warnings),
        timings=timings,
        expanded_tei_path=expanded_tei,
        expanded_txt_path=expanded_txt,
    )


def load_prompt_cfg(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return load_prompt_cfg_from_str(text, suffix=path.suffix.lower())


def load_prompt_cfg_from_str(text: str, *, suffix: str = "") -> dict:
    t = text.strip()
    if suffix == ".json":
        data = json.loads(t)
    elif t.startswith("{"):
        data = json.loads(t)
    else:
        data = yaml.safe_load(t)
    if not isinstance(data, dict):
        raise ValueError("prompt file must parse to a JSON/YAML object (top-level mapping), not a list or scalar")
    return data


def set_normalization_mode_for_diplomatic(cfg: dict[str, Any], *, diplomatic: bool) -> None:
    """Set ``normalizationMode`` from the diplomatic toggle (GUI / CLI / API).

    When *diplomatic* is false, the LLM emits a parallel ``normalizedLayer`` for expansions
    (protocol ``normalizationMode: normalized``). When true, only the diplomatic transcript is produced.
    """
    cfg["normalizationMode"] = "diplomatic" if diplomatic else "normalized"
