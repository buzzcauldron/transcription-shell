"""Discover images and run the pipeline for each (sequential)."""

from __future__ import annotations

import glob
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from transcriber_shell.config import Settings
from transcriber_shell.llm.validate_output import (
    load_transcription_root,
    load_yaml_or_json_path,
    validate_transcript_file,
)
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.run import run_pipeline
from transcriber_shell.pipeline.transcription_paths import transcription_yaml_path

IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
)
PDF_SUFFIX = ".pdf"
INPUT_SUFFIXES = IMAGE_SUFFIXES | {PDF_SUFFIX}


def _expand_pdf(pdf_path: Path) -> list[Path]:
    """Rasterise a PDF into images under the artifacts cache and return their paths."""
    from transcriber_shell.pipeline.pdf_extract import expand_pdf_to_images

    s = Settings()
    return expand_pdf_to_images(pdf_path, s.artifacts_dir, dpi=s.pdf_dpi)


def sanitize_job_id(stem: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._-")
    return (s[:120] if s else "job")


def _htr_results_for_report(htr: dict[str, Any]) -> dict[str, Any] | None:
    """JSON-serializable summary of HTR backend results for batch reports."""
    if not htr:
        return None
    from transcriber_shell.htr.base import HtrResult

    out: dict[str, Any] = {}
    for name, v in htr.items():
        if isinstance(v, Exception):
            out[name] = {"error": str(v)}
        elif isinstance(v, HtrResult):
            preview = v.text[:800] + ("…" if len(v.text) > 800 else "")
            out[name] = {
                "backend": v.backend,
                "line_count": v.line_count,
                "confidence": v.confidence,
                "text_preview": preview,
            }
        else:
            out[name] = {"repr": repr(v)}
    return out


def discover_images(path_or_glob: str) -> list[Path]:
    """Resolve a path/glob into image paths. PDFs are rasterised to per-page JPGs."""
    def _expand(paths: list[Path]) -> list[Path]:
        out: list[Path] = []
        for x in paths:
            if not x.is_file():
                continue
            suf = x.suffix.lower()
            if suf in IMAGE_SUFFIXES:
                out.append(x)
            elif suf == PDF_SUFFIX:
                out.extend(_expand_pdf(x))
        return out

    raw = path_or_glob.strip()
    if any(ch in raw for ch in "*?["):
        return _expand([Path(p) for p in sorted(glob.glob(raw, recursive=True))])
    p = Path(raw).expanduser().resolve()
    if p.is_file():
        return _expand([p])
    if p.is_dir():
        return sorted(_expand(sorted(p.iterdir())), key=lambda q: q.name)
    return []


def transcription_segment_count(path: Path) -> int:
    """Best-effort count of protocol ``segments`` in an existing transcription YAML/JSON file."""
    try:
        data = load_yaml_or_json_path(path)
    except (OSError, ValueError, yaml.YAMLError):
        return 0
    root = load_transcription_root(data)
    if not isinstance(root, dict):
        return 0
    segs = root.get("segments")
    return len(segs) if isinstance(segs, list) else 0


def resolve_lines_xml_for_image(
    image: Path,
    *,
    skip_gm: bool,
    lines_xml: Path | None,
    lines_xml_dir: Path | None,
    n_images: int,
) -> Path | None:
    """Return path to lines XML when skip_gm; otherwise None (lineation backend fetches per job)."""
    if not skip_gm:
        return None
    if lines_xml_dir is not None:
        candidate = lines_xml_dir / f"{image.stem}.xml"
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(
            f"Skip Glyph Machina + batch: need one lines XML per image stem. "
            f"Missing file: {candidate} (under --lines-xml-dir). "
            f"Expected filename '{image.stem}.xml' next to image '{image.name}'."
        )
    if lines_xml is not None:
        if n_images != 1:
            raise ValueError(
                "Skip Glyph Machina: --lines-xml applies only when there is exactly one image. "
                "For multiple images use --lines-xml-dir with <image_stem>.xml for each page."
            )
        return lines_xml.resolve()
    raise ValueError(
        "Skip Glyph Machina requires --lines-xml (single image) or --lines-xml-dir (folder of per-page XML files)."
    )


def run_batch(
    images: list[Path],
    prompt_cfg: dict[str, Any],
    *,
    provider: str,
    model_override: str | None,
    skip_gm: bool,
    lines_xml: Path | None,
    lines_xml_dir: Path | None,
    xsd_path: Path | None,
    require_text_line: bool,
    skip_lines_xml_validation: bool = False,
    skip_successful: bool = False,
    document_job_id: str | None = None,
    settings: Settings | None = None,
    log_fn=None,
    cancel_check=None,
) -> list[dict[str, Any]]:
    """Run pipeline for each image; return report rows (dicts).

    ``log_fn`` (optional) is forwarded to ``run_pipeline`` so per-stage
    progress (lineation / HTR / LLM start+done with elapsed) streams live.
    A per-image header ``[i/N] image=…`` is logged at the start of each
    iteration so the operator can tell how far through the batch we are.

    ``cancel_check`` (optional) is a zero-arg callable that returns True
    when the operator has requested cancellation. Polled before each
    iteration; if true, the loop breaks and rows already produced are
    returned. Currently-running pipelines complete their stage — there is
    no mid-stage abort. Designed for the GUI Stop button.
    """
    def _log(msg: str) -> None:
        if log_fn is not None:
            log_fn(msg)

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    s = settings or Settings()
    n = len(images)
    workers = max(1, min(int(getattr(s, "batch_parallel_pages", 1) or 1), n))

    def _process(i: int, image: Path) -> dict[str, Any] | None:
        """Run the pipeline for a single image. Returns the report row, or None if cancelled."""
        if _cancelled():
            return None
        job_id = document_job_id if document_job_id else sanitize_job_id(image.stem)
        _log(f"[{i}/{n}] image={image.name}  job_id={job_id}")
        if skip_successful and has_successful_transcription(
            job_id, image, settings=s
        ):
            ty_path = transcription_yaml_path(s.artifacts_dir, job_id, image)
            seg_n = transcription_segment_count(ty_path)
            _log(f"[{i}/{n}] skipped (existing valid transcription)")
            return {
                "job_id": job_id,
                "image": str(image),
                "ok": True,
                "skipped": True,
                "errors": [],
                "warnings": [
                    "Skipped: existing valid transcription file "
                    f"({image.stem}_transcription.yaml) found."
                ],
                # PageXML TextLine count was not recomputed; GUI/CLI show segment count separately.
                "text_line_count": None,
                "transcription_segment_count": seg_n,
                "lines_xml": None,
                "transcription_yaml": str(ty_path.resolve()),
            }
        lx: Path | None = None
        try:
            if skip_gm:
                lx = resolve_lines_xml_for_image(
                    image,
                    skip_gm=True,
                    lines_xml=lines_xml,
                    lines_xml_dir=lines_xml_dir,
                    n_images=n,
                )
        except (FileNotFoundError, ValueError) as e:
            _log(f"[{i}/{n}] fail (skip_gm resolution): {e}")
            return {
                "job_id": job_id,
                "image": str(image),
                "ok": False,
                "errors": [str(e)],
                "text_line_count": 0,
                "lines_xml": None,
                "transcription_yaml": None,
            }

        job = TranscribeJob(
            job_id=job_id,
            image_path=image.resolve(),
            prompt_cfg=prompt_cfg,
            provider=provider,
            model_override=model_override,
        )
        # Prefix per-stage messages with the page index when running parallel so the
        # interleaved log stays readable.
        def _stage_log(msg: str) -> None:
            if workers > 1:
                _log(f"[{i}/{n}] {msg}")
            else:
                _log(msg)

        res = run_pipeline(
            job,
            skip_gm=skip_gm,
            lines_xml_path=lx,
            xsd_path=xsd_path,
            require_text_line=require_text_line,
            skip_lines_xml_validation=skip_lines_xml_validation,
            settings=s,
            log_fn=_stage_log,
        )
        _log(
            f"[{i}/{n}] {'ok' if not res.errors else 'fail'}  text_lines={res.text_line_count}"
        )
        lxml_str = str(res.lines_xml_path) if res.lines_xml_path else None
        # When multiple pages share one job_id folder, rename the generic "lines.xml"
        # to "<image_stem>_lines.xml" so each page's lineation file coexists and the
        # canonical "lines.xml" slot stays free for the next page's lineation check.
        if document_job_id and lxml_str:
            lxml = Path(lxml_str)
            if lxml.name == "lines.xml":
                named = lxml.parent / f"{image.stem}_lines.xml"
                try:
                    lxml.rename(named)
                    lxml_str = str(named)
                except OSError:
                    pass
        return {
            "job_id": res.job_id,
            "image": str(image),
            "ok": len(res.errors) == 0,
            "errors": res.errors,
            "warnings": res.warnings,
            "text_line_count": res.text_line_count,
            "lines_xml": lxml_str,
            "transcription_yaml": str(res.transcription_yaml_path)
            if res.transcription_yaml_path
            else None,
            "llm_usage": res.llm_usage,
            "htr_results": _htr_results_for_report(res.htr_results),
        }

    if workers <= 1:
        # Serial path — preserves the simple, ordered log cadence operators are used to.
        rows: list[dict[str, Any]] = []
        for i, image in enumerate(images, 1):
            if _cancelled():
                _log(f"[{i}/{n}] stop requested — halting batch (rows so far: {len(rows)})")
                break
            row = _process(i, image)
            if row is not None:
                rows.append(row)
        return rows

    # Parallel path — pages are independent, so a small pool overlaps LLM I/O wait
    # with the next page's lineation. Order in the returned rows matches image order.
    _log(f"parallel pages: {workers}")
    indexed: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process, i, img): i for i, img in enumerate(images, 1)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001 — one bad page shouldn't kill the batch
                _log(f"[{i}/{n}] fail (worker exception): {exc}")
                indexed[i] = {
                    "job_id": document_job_id or sanitize_job_id(images[i - 1].stem),
                    "image": str(images[i - 1]),
                    "ok": False,
                    "errors": [f"worker exception: {exc}"],
                    "text_line_count": 0,
                    "lines_xml": None,
                    "transcription_yaml": None,
                }
                continue
            if row is not None:
                indexed[i] = row
    return [indexed[i] for i in sorted(indexed)]


def write_combined_document(
    rows: list[dict[str, Any]],
    out_dir: Path,
    *,
    include_translation: bool = False,
    log_fn=None,
) -> tuple[Path | None, Path | None]:
    """Collate per-page outputs into a single paginated document.

    Writes ``full_transcription.txt`` (and optionally ``full_translation.txt``)
    into *out_dir*.  Pages are ordered by the row list order, which matches the
    original image order.  Returns ``(transcription_path, translation_path)``.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    tx_parts: list[str] = []
    tr_parts: list[str] = []

    for i, row in enumerate(rows, 1):
        yaml_path_str = row.get("transcription_yaml")
        if not yaml_path_str:
            continue
        yaml_path = Path(yaml_path_str)

        # Plain-text transcription
        txt_path = yaml_path.with_suffix(".txt")
        if txt_path.exists():
            text = txt_path.read_text(encoding="utf-8").strip()
        else:
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                root = data.get("transcriptionOutput", data) if isinstance(data, dict) else {}
                segs = root.get("segments") or [] if isinstance(root, dict) else []
                text = "\n\n".join(
                    s["text"].strip() for s in segs
                    if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip()
                )
            except Exception:
                text = ""
        if text:
            image_name = Path(row.get("image", f"page {i}")).name
            tx_parts.append(f"[Page {i}: {image_name}]\n{text}")

        # Translation sidecar
        if include_translation:
            tr_path = yaml_path.parent / (yaml_path.stem.replace("_transcription", "") + "_translation.txt")
            if not tr_path.exists():
                tr_path = yaml_path.with_name(yaml_path.stem + "_translation.txt")
            if tr_path.exists():
                tr_text = tr_path.read_text(encoding="utf-8").strip()
                if tr_text:
                    image_name = Path(row.get("image", f"page {i}")).name
                    tr_parts.append(f"[Page {i}: {image_name}]\n{tr_text}")

    out_dir.mkdir(parents=True, exist_ok=True)
    tx_out: Path | None = None
    tr_out: Path | None = None

    if tx_parts:
        tx_out = out_dir / "full_transcription.txt"
        tx_out.write_text("\n\n---\n\n".join(tx_parts) + "\n", encoding="utf-8")
        _log(f"combined transcription: {tx_out}")

    if tr_parts:
        tr_out = out_dir / "full_translation.txt"
        tr_out.write_text("\n\n---\n\n".join(tr_parts) + "\n", encoding="utf-8")
        _log(f"combined translation: {tr_out}")

    return tx_out, tr_out


def has_successful_transcription(
    job_id: str,
    image_path: Path,
    *,
    settings: Settings | None = None,
) -> bool:
    """True when artifacts/<job_id>/<image_stem>_transcription.yaml exists and validates cleanly."""
    s = settings or Settings()
    p = transcription_yaml_path(s.artifacts_dir, job_id, image_path)
    if not p.is_file() or p.stat().st_size == 0:
        return False
    ok, _errs, _warns = validate_transcript_file(p, settings=s)
    return ok


def write_batch_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
