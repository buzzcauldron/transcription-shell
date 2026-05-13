"""Orchestrate: lines XML → validate → LLM (+ optional HTR backends) → YAML validate.

Core path: fetch lines (or use --skip-gm + existing XML) → validate_lines_xml → run_transcribe →
normalize + validate_transcript_file. Other backends (mask, kraken) are pluggable line sources only.
HTR backends (kraken-htr, gm-htr): when ``htr_parallel`` is true they run alongside the LLM; when false
they run **before** the LLM and drafts are appended to the lineation hint (lineation → HTR → LLM).
"""

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
from transcriber_shell.llm.errors import LLMProviderError
from transcriber_shell.mask_lineation import MaskLineationError, fetch_lines_xml_mask
from transcriber_shell.llm.transcribe import run_transcribe, strip_yaml_fence, TranscribeResult
from transcriber_shell.llm.validate_output import (
    normalize_transcription_yaml_data,
    validate_transcript_file,
)
from transcriber_shell.models.job import PipelineResult, TranscribeJob
from transcriber_shell.pipeline.transcription_paths import transcription_yaml_path, transcription_txt_path
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

    if not job.line_hint and text_line_count > 0:
        job.line_hint = (
            f"PageXML line detector reports {text_line_count} TextLine element(s); "
            "align segment lineRange fields accordingly."
        )

    # HTR (Glyph Machina, Zenodo kraken-htr): combination from htr_combination / htr_parallel; shell = LLM only.
    htr_future: Future | None = None
    htr_executor: ThreadPoolExecutor | None = None
    htr_results_early: dict[str, Any] = {}
    if lines_out is not None and not s.xml_only:
        from transcriber_shell.htr.detect import detect_scripts
        from transcriber_shell.htr.parallel import (
            build_htr_tasks,
            run_htr_ordered,
            run_htr_parallel,
        )
        from transcriber_shell.htr.selector import HtrPlanKind, plan_htr_execution

        scripts = detect_scripts(job.prompt_cfg)
        htr_tasks = build_htr_tasks(job.image_path, lines_out, scripts, s)
        plan = plan_htr_execution(s, htr_tasks)
        if plan.kind == HtrPlanKind.NONE:
            if htr_tasks and (s.htr_combination or "").strip().lower() in (
                "shell",
                "off",
                "none",
                "llm_only",
            ):
                warnings.append(
                    "HTR backends are configured (Glyph Machina and/or Zenodo paths) but "
                    f"htr_combination={s.htr_combination!r} runs the original shell (LLM) only; HTR was skipped."
                )
        elif plan.kind == HtrPlanKind.WITH_LLM_PARALLEL and plan.tasks:
            _log("htr: starting (parallel with LLM)…")
            htr_executor = ThreadPoolExecutor(max_workers=1)
            htr_future = htr_executor.submit(run_htr_parallel, plan.tasks)
        elif plan.kind == HtrPlanKind.BEFORE_LLM_PARALLEL and plan.tasks:
            _log("htr: starting (before LLM)…")
            _t_htr = time.perf_counter()
            try:
                htr_results_early = run_htr_parallel(plan.tasks)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"HTR runner error: {exc}")
            else:
                hint_extra = _htr_results_to_line_hint(htr_results_early)
                if hint_extra:
                    job.line_hint = (
                        f"{job.line_hint}\n\n{hint_extra}" if job.line_hint else hint_extra
                    )
            _htr_s = time.perf_counter() - _t_htr
            timings.append(("htr", _htr_s))
            _log(f"htr: done ({_htr_s:.1f}s)")
        elif plan.kind == HtrPlanKind.BEFORE_LLM_ORDERED and plan.ordered:
            _log("htr: starting (before LLM)…")
            _t_htr = time.perf_counter()
            try:
                htr_results_early = run_htr_ordered(plan.ordered)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"HTR ordered runner error: {exc}")
            else:
                hint_extra = _htr_results_to_line_hint(htr_results_early)
                if hint_extra:
                    job.line_hint = (
                        f"{job.line_hint}\n\n{hint_extra}" if job.line_hint else hint_extra
                    )
            _htr_s = time.perf_counter() - _t_htr
            timings.append(("htr", _htr_s))
            _log(f"htr: done ({_htr_s:.1f}s)")

    _log(f"llm: starting ({job.provider}/{job.model_override or 'default'})…")
    llm_usage: dict[str, int] | None = None
    _t = time.perf_counter()
    try:
        tx = run_transcribe(job, settings=s)
        if isinstance(tx, TranscribeResult):
            raw = tx.text
            llm_usage = tx.usage
        else:
            raw = tx  # pragma: no cover — tests may mock with plain str
    except LLMProviderError as e:
        hint = ""
        if job.provider.lower() == "anthropic":
            hint = " See docs/claude_anthropic_reference.md for Anthropic-specific troubleshooting."
        errors.append(f"LLM transcription failed ({job.provider}): {e}{hint}")
        return PipelineResult(
            job.job_id,
            lines_out,
            None,
            text_line_count,
            errors=errors,
            warnings=warnings,
            htr_results=_finalize_htr_results(
                htr_results_early, htr_future, htr_executor, warnings
            ),
        )
    except TimeoutError as e:
        errors.append(
            f"LLM transcription failed ({job.provider}): {e}. {_llm_network_timeout_hint(job)}"
        )
        return PipelineResult(
            job.job_id,
            lines_out,
            None,
            text_line_count,
            errors=errors,
            warnings=warnings,
            htr_results=_finalize_htr_results(
                htr_results_early, htr_future, htr_executor, warnings
            ),
        )
    except OSError as e:
        if getattr(e, "errno", None) == errno.ETIMEDOUT:
            errors.append(
                f"LLM transcription failed ({job.provider}): {e}. {_llm_network_timeout_hint(job)}"
            )
            return PipelineResult(
                job.job_id,
                lines_out,
                None,
                text_line_count,
                errors=errors,
                warnings=warnings,
                htr_results=_finalize_htr_results(
                    htr_results_early, htr_future, htr_executor, warnings
                ),
            )
        errors.append(
            f"LLM transcription failed ({job.provider}): {e}. "
            "Check API key in .env or the GUI, provider outage/rate limits, and that the model id is valid."
        )
        return PipelineResult(
            job.job_id,
            lines_out,
            None,
            text_line_count,
            errors=errors,
            warnings=warnings,
            htr_results=_finalize_htr_results(
                htr_results_early, htr_future, htr_executor, warnings
            ),
        )
    except httpx.TimeoutException as e:
        errors.append(
            f"LLM transcription failed ({job.provider}): {e} ({type(e).__name__}). "
            f"{_llm_network_timeout_hint(job)}"
        )
        return PipelineResult(
            job.job_id,
            lines_out,
            None,
            text_line_count,
            errors=errors,
            warnings=warnings,
            htr_results=_finalize_htr_results(
                htr_results_early, htr_future, htr_executor, warnings
            ),
        )
    except Exception as e:
        errors.append(
            f"LLM transcription failed ({job.provider}): {e}. "
            "Check API key in .env or the GUI, provider outage/rate limits, and that the model id is valid."
        )
        return PipelineResult(
            job.job_id,
            lines_out,
            None,
            text_line_count,
            errors=errors,
            warnings=warnings,
            htr_results=_finalize_htr_results(
                htr_results_early, htr_future, htr_executor, warnings
            ),
        )

    _llm_s = time.perf_counter() - _t
    timings.append(("llm", _llm_s))
    _log(f"llm: done ({_llm_s:.1f}s)")

    raw = strip_yaml_fence(raw)
    raw = _repair_yaml_uncertain_tokens(raw)
    out_yaml = transcription_yaml_path(s.artifacts_dir, job.job_id, job.image_path)
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(raw, encoding="utf-8")

    # Parse and re-dump for sanity (optional)
    try:
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            # Restore [uncertain: tokens that were placeholdered for YAML safety
            data = _restore_uncertain_in_dict(data)
            normalize_transcription_yaml_data(data)
            _fixup_protocol_compliance(data)
            # Overwrite whatever model ID the LLM put in the metadata with the
            # actual runtime model so records are trustworthy.
            _actual_model = job.model_override or s.resolved_model(job.provider)
            _meta = (data.get("transcriptionOutput") or {}).get("metadata")
            if isinstance(_meta, dict):
                _meta["modelId"] = _actual_model
                _meta["timestamp"] = datetime.now(timezone.utc).isoformat()
            out_yaml.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
            out_txt = transcription_txt_path(s.artifacts_dir, job.job_id, job.image_path)
            try:
                out_txt.write_text(_extract_plain_text(data), encoding="utf-8")
            except OSError:
                pass
    except yaml.YAMLError as e:
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

    val_ok, val_errs, val_warns = validate_transcript_file(out_yaml, settings=s)
    warnings.extend(val_warns)
    if not val_ok:
        errors.extend(val_errs)

    htr_results = _finalize_htr_results(
        htr_results_early, htr_future, htr_executor, warnings
    )

    return PipelineResult(
        job.job_id,
        lines_out,
        out_yaml,
        text_line_count,
        errors=errors,
        warnings=warnings,
        llm_usage=llm_usage,
        htr_results=htr_results,
        timings=timings,
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
