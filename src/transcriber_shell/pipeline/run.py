"""Orchestrate: lines XML → validate → LLM → YAML validate.

Core path: fetch lines (or use --skip-gm + existing XML) → validate_lines_xml → run_transcribe →
normalize + validate_transcript_file. Other backends (mask, kraken) are pluggable line sources only.
"""

from __future__ import annotations

import errno
import json
from pathlib import Path

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
from transcriber_shell.pipeline.transcription_paths import transcription_yaml_path
from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional


def _approximate_text_line_count(lines_xml: Path) -> int:
    """Best-effort TextLine count when full validation is skipped."""
    try:
        text = lines_xml.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return text.count("<TextLine")


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
    parts.append(
        "If you use a proxy, set TRANSCRIBER_SHELL_LLM_USE_PROXY and/or "
        "TRANSCRIBER_SHELL_LLM_HTTP_PROXY when appropriate."
    )
    return " ".join(parts)


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
) -> PipelineResult:
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

    lines_out: Path | None = None
    text_line_count = 0

    if skip_gm:
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
        try:
            backend = s.lineation_backend
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

    llm_usage: dict[str, int] | None = None
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
        )

    raw = strip_yaml_fence(raw)
    out_yaml = transcription_yaml_path(s.artifacts_dir, job.job_id, job.image_path)
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(raw, encoding="utf-8")

    # Parse and re-dump for sanity (optional)
    try:
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            normalize_transcription_yaml_data(data)
            out_yaml.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
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
        )

    val_ok, val_errs, val_warns = validate_transcript_file(out_yaml, settings=s)
    warnings.extend(val_warns)
    if not val_ok:
        errors.extend(val_errs)

    return PipelineResult(
        job.job_id,
        lines_out,
        out_yaml,
        text_line_count,
        errors=errors,
        warnings=warnings,
        llm_usage=llm_usage,
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
