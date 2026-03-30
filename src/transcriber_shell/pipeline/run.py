"""Orchestrate: optional Glyph Machina → XML validate → LLM transcribe → YAML validate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from transcriber_shell.config import Settings
from transcriber_shell.glyph_machina.workflow import GlyphMachinaError, fetch_lines_xml
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
) -> PipelineResult:
    s = settings or Settings()
    errors: list[str] = []
    warnings: list[str] = []

    lines_out: Path | None = None
    text_line_count = 0

    if skip_gm:
        if not lines_xml_path or not lines_xml_path.is_file():
            errors.append("skip_gm requires existing --lines-xml path")
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
            lines_out = fetch_lines_xml(job.image_path, job.job_id, settings=s)
        except GlyphMachinaError as e:
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
        errors.append("lines XML validation failed")
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
    except Exception as e:
        errors.append(f"LLM transcription failed: {e}")
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
        errors.append(f"model output is not valid YAML: {e}")
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
        raise ValueError("prompt must be a JSON/YAML object")
    return data
