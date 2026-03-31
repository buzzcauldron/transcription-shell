"""Orchestrate: lineation (mask / Kraken / Glyph Machina) → XML validate → LLM → YAML validate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from transcriber_shell.config import LineationBackend, Settings
from transcriber_shell.glyph_machina.workflow import GlyphMachinaError, fetch_lines_xml
from transcriber_shell.kraken_lineation import KrakenLineationError, fetch_lines_xml_kraken
from transcriber_shell.llm.errors import LLMProviderError
from transcriber_shell.mask_lineation import MaskLineationError, fetch_lines_xml_mask
from transcriber_shell.llm.transcribe import run_transcribe, strip_yaml_fence
from transcriber_shell.llm.validate_output import validate_transcript_file
from transcriber_shell.models.job import PipelineResult, TranscribeJob
from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional


def run_pipeline(
    job: TranscribeJob,
    *,
    skip_gm: bool = False,
    lines_xml_path: Path | None = None,
    xsd_path: Path | None = None,
    require_text_line: bool = True,
    settings: Settings | None = None,
    lineation_backend: LineationBackend | None = None,
) -> PipelineResult:
    s = settings or Settings()
    if lineation_backend is not None:
        s = s.model_copy(update={"lineation_backend": lineation_backend})
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
            errors.append(str(e))
            return PipelineResult(
                job.job_id,
                None,
                None,
                0,
                errors=errors,
                warnings=warnings,
            )

    ok, xml_msgs, stats = validate_lines_xml(str(lines_out), require_text_line=require_text_line)
    warnings.extend(m for m in xml_msgs if m.startswith("warning:"))
    errors.extend(m for m in xml_msgs if m.startswith("error:"))
    if not ok:
        errors.append(
            "Lines XML did not pass validation (well-formed XML, TextLine rules, or optional checks). "
            "See detailed messages above; try unchecking 'Require ≥1 TextLine' if your file has no TextLine yet."
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

    if not job.line_hint and text_line_count > 0:
        job.line_hint = (
            f"PageXML line detector reports {text_line_count} TextLine element(s); "
            "align segment lineRange fields accordingly."
        )

    try:
        raw = run_transcribe(job, settings=s)
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
    out_yaml = (s.artifacts_dir / job.job_id / "transcription.yaml").resolve()
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(raw, encoding="utf-8")

    # Parse and re-dump for sanity (optional)
    try:
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
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
