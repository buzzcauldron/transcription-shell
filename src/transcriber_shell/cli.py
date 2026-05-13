"""CLI: transcriber-shell."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.llm.validate_output import validate_transcript_file
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.batch import (
    discover_images,
    has_successful_transcription,
    run_batch,
    write_batch_report,
)
from transcriber_shell.pipeline.run import load_prompt_cfg, run_pipeline
from transcriber_shell.pipeline.transcription_paths import transcription_yaml_path
from transcriber_shell.xml_tools.lines_compare import compare_lines_xml, format_comparison_report
from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
from transcriber_shell.xml_tools.validate_gt_pagexml import validate_gt_pagexml
from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional


# ── doc-type helpers ─────────────────────────────────────────────────────────

def _apply_doc_type(
    doc_type: str | None,
    settings: Settings,
    prompt_arg: str | None,
) -> tuple[Settings, str | None]:
    """Load doc-type spec and apply it to settings + prompt path.

    Returns (updated_settings, resolved_prompt_path_str).
    CLI args always win over spec defaults.
    """
    if not doc_type:
        return settings, prompt_arg

    from transcriber_shell.document_types import load_doc_type, list_doc_types

    extra = [settings.document_types_dir] if settings.document_types_dir else []
    try:
        spec = load_doc_type(doc_type, extra_dirs=extra)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)

    updates: dict = {}

    # Provider / model — only override when not already set in env/cli
    if not settings.default_model:
        updates["default_provider"] = spec.primary_provider
        updates["default_model"] = spec.primary_model

    # HTR model — only when not already set in env
    if spec.htr_path and not settings.kraken_htr_model_path:
        updates["kraken_htr_model_path"] = spec.htr_path

    # Seg model — only when not already set in env
    if spec.seg_path and not settings.kraken_model_path:
        updates["kraken_model_path"] = spec.seg_path

    new_settings = settings.model_copy(update=updates) if updates else settings

    # Prompt — CLI arg wins; otherwise resolve from spec
    resolved_prompt = prompt_arg
    if resolved_prompt is None:
        pp = spec.prompt_path()
        if pp:
            resolved_prompt = str(pp)
        else:
            # fallback: look alongside the cli's own prompt default
            resolved_prompt = spec.prompt

    return new_settings, resolved_prompt


def cmd_test_htr(args: argparse.Namespace) -> int:
    from transcriber_shell.htr.eval import evaluate, format_eval_report

    model = Path(args.model).expanduser().resolve()
    gt = Path(args.gt).expanduser().resolve()
    seg_model = Path(args.seg_model).expanduser().resolve() if args.seg_model else None

    if not model.exists():
        print(f"error: model not found: {model}", file=sys.stderr)
        return 1
    if not gt.exists():
        print(f"error: ground-truth path not found: {gt}", file=sys.stderr)
        return 1

    try:
        result = evaluate(
            model,
            gt,
            seg_model=seg_model,
            device=args.device,
            centroid_match_px=args.centroid_match_px,
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(format_eval_report(result, as_json=args.json), end="")
    return 0 if result.transcription is not None else 1


def cmd_compare_lines_xml(args: argparse.Namespace) -> int:
    try:
        result = compare_lines_xml(
            args.reference,
            args.hypothesis,
            centroid_match_px=args.centroid_match_px,
        )
    except (OSError, ET.ParseError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    text = format_comparison_report(result, as_json=args.json)
    print(text, end="")
    return 0


def cmd_validate_gt_pagexml_cli(args: argparse.Namespace) -> int:
    ok, lines = validate_gt_pagexml(args.xml, args.image)
    for line in lines:
        if line.startswith("error:"):
            print(line, file=sys.stderr)
        else:
            print(line)
    return 0 if ok else 1


def cmd_validate_xml(args: argparse.Namespace) -> int:
    ok, msgs, stats = validate_lines_xml(args.file, require_text_line=args.require_text_line)
    for m in msgs:
        print(m, file=sys.stderr)
    if stats:
        print(
            "text_line={text_line} text_region={text_region} line={line}".format(**stats)
        )
    if args.xsd:
        xsd_ok, xsd_errs = validate_xsd_optional(Path(args.file), Path(args.xsd))
        for e in xsd_errs:
            print(e, file=sys.stderr)
        ok = ok and xsd_ok
    return 0 if ok else 1


def cmd_validate_yaml(args: argparse.Namespace) -> int:
    ok, errs, warns = validate_transcript_file(Path(args.file))
    for w in warns:
        print(w, file=sys.stderr)
    if not ok:
        for e in errs:
            print(e, file=sys.stderr)
        return 1
    return 0


def _resolve_provider(cli_provider: str | None, settings: Settings) -> str:
    return (cli_provider or settings.default_provider).lower()


def _resolve_xsd_path(cli_xsd: str | None, settings: Settings) -> Path | None:
    """CLI --xsd wins; else optional TRANSCRIBER_SHELL_LINES_XML_XSD from settings."""
    if cli_xsd:
        return Path(cli_xsd).expanduser().resolve()
    if settings.lines_xml_xsd:
        return settings.lines_xml_xsd.expanduser().resolve()
    return None


def _expand_resolve_cli_path(arg: str | None) -> Path | None:
    """User-typed paths may use ``~``; expand before resolve."""
    if not arg:
        return None
    return Path(arg).expanduser().resolve()


def _require_text_line_from_cli(args: argparse.Namespace, settings: Settings) -> bool:
    """--no-require-text-line forces False; else use settings.xml_require_text_line."""
    if getattr(args, "no_require_text_line", False):
        return False
    return settings.xml_require_text_line


def _skip_lines_xml_validation_from_cli(args: argparse.Namespace, settings: Settings) -> bool:
    """--skip-lines-xml-validation forces True; else use settings.skip_lines_xml_validation."""
    if getattr(args, "skip_lines_xml_validation", False):
        return True
    return settings.skip_lines_xml_validation


def _pipeline_settings(args: argparse.Namespace) -> Settings:
    """Apply optional CLI overrides for LLM proxy and Glyph Machina browser profile."""
    s = Settings()
    updates: dict = {}
    if getattr(args, "llm_proxy", None):
        updates["llm_use_proxy"] = True
        updates["llm_http_proxy"] = args.llm_proxy
    if getattr(args, "gm_persistent_profile", False):
        updates["gm_persistent_profile"] = True
    if getattr(args, "gm_user_data_dir", None):
        updates["gm_user_data_dir"] = Path(args.gm_user_data_dir).expanduser()
    if getattr(args, "continue_on_lineation_failure", False):
        updates["continue_on_lineation_failure"] = True
    if getattr(args, "xml_only", False):
        updates["xml_only"] = True
    if getattr(args, "htr_combination", None):
        updates["htr_combination"] = args.htr_combination
    elif getattr(args, "htr_sequential", False):
        updates["htr_parallel"] = False
    if updates:
        return s.model_copy(update=updates)
    return s


def _add_pipeline_network_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--llm-proxy",
        metavar="URL",
        default=None,
        help="HTTP(S) proxy for cloud LLM APIs (enables TRANSCRIBER_SHELL_LLM_USE_PROXY)",
    )
    p.add_argument(
        "--gm-persistent-profile",
        action="store_true",
        help="Use persistent Chromium profile for Glyph Machina (cookies / login)",
    )
    p.add_argument(
        "--gm-user-data-dir",
        metavar="PATH",
        default=None,
        help="Chromium user data dir for --gm-persistent-profile (default: env or ~/.cache/...)",
    )


def cmd_run(args: argparse.Namespace) -> int:
    settings = _pipeline_settings(args)
    if getattr(args, "lineation_backend", None):
        settings = settings.model_copy(
            update={"lineation_backend": args.lineation_backend}
        )
    settings, prompt_path = _apply_doc_type(
        getattr(args, "doc_type", None), settings, getattr(args, "prompt", None)
    )
    if not prompt_path:
        print("error: --prompt is required (or set --doc-type with a spec that includes a prompt)", file=sys.stderr)
        return 1
    cfg = load_prompt_cfg(Path(prompt_path))
    if getattr(args, "diplomatic", None) is not None:
        cfg["normalizationMode"] = "diplomatic" if args.diplomatic else "normalized"
    provider = _resolve_provider(args.provider, settings)
    job = TranscribeJob(
        job_id=args.job_id,
        image_path=Path(args.image),
        prompt_cfg=cfg,
        provider=provider,
        model_override=args.model,
    )
    if args.skip_successful and has_successful_transcription(
        job.job_id, job.image_path, settings=settings
    ):
        out = transcription_yaml_path(
            settings.artifacts_dir, job.job_id, job.image_path
        )
        print(
            f"skipped job_id={job.job_id} reason=existing_valid_transcription "
            f"path={out}"
        )
        return 0
    lines_xml = _expand_resolve_cli_path(args.lines_xml)
    xsd = _resolve_xsd_path(args.xsd, settings)
    res = run_pipeline(
        job,
        skip_gm=args.skip_gm,
        lines_xml_path=lines_xml,
        xsd_path=xsd,
        require_text_line=_require_text_line_from_cli(args, settings),
        skip_lines_xml_validation=_skip_lines_xml_validation_from_cli(args, settings),
        settings=settings,
    )
    for w in res.warnings:
        print(w, file=sys.stderr)
    if res.lines_xml_path:
        print(f"lines_xml={res.lines_xml_path}")
    if res.transcription_yaml_path:
        print(f"transcription_yaml={res.transcription_yaml_path}")
    print(f"text_line_count={res.text_line_count}")
    if res.errors:
        for e in res.errors:
            print(e, file=sys.stderr)
        return 1
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    settings = _pipeline_settings(args)
    if getattr(args, "lineation_backend", None):
        settings = settings.model_copy(
            update={"lineation_backend": args.lineation_backend}
        )
    settings, prompt_path = _apply_doc_type(
        getattr(args, "doc_type", None), settings, getattr(args, "prompt", None)
    )
    if not prompt_path:
        print("error: --prompt is required (or set --doc-type with a spec that includes a prompt)", file=sys.stderr)
        return 1
    images = discover_images(args.path)
    if not images:
        print("No images found (supported: .jpg, .jpeg, .png, .webp, …)", file=sys.stderr)
        return 2
    cfg = load_prompt_cfg(Path(prompt_path))
    if getattr(args, "diplomatic", None) is not None:
        cfg["normalizationMode"] = "diplomatic" if args.diplomatic else "normalized"
    provider = _resolve_provider(args.provider, settings)
    lines_xml = _expand_resolve_cli_path(args.lines_xml)
    lines_xml_dir = _expand_resolve_cli_path(args.lines_xml_dir)
    xsd = _resolve_xsd_path(args.xsd, settings)
    rows = run_batch(
        images,
        cfg,
        provider=provider,
        model_override=args.model,
        skip_gm=args.skip_gm,
        lines_xml=lines_xml,
        lines_xml_dir=lines_xml_dir,
        xsd_path=xsd,
        require_text_line=_require_text_line_from_cli(args, settings),
        skip_lines_xml_validation=_skip_lines_xml_validation_from_cli(args, settings),
        skip_successful=args.skip_successful,
        settings=settings,
    )
    if args.batch_report:
        write_batch_report(Path(args.batch_report), rows)
        print(f"batch_report={args.batch_report}")
    ok_all = all(r.get("ok") for r in rows)
    for r in rows:
        status = "ok" if r.get("ok") else "fail"
        print(f"[{status}] job_id={r.get('job_id')} image={r.get('image')}")
        if not r.get("ok"):
            for e in r.get("errors") or []:
                print(f"  error: {e}", file=sys.stderr)
    return 0 if ok_all else 1


def cmd_gui(_args: argparse.Namespace) -> int:
    from transcriber_shell.gui import main as gui_main

    gui_main()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as e:
        print("Install API extra: pip install 'transcriber-shell[api]'", file=sys.stderr)
        raise SystemExit(2) from e
    settings = Settings()
    host = args.host or settings.api_host
    port = args.port or settings.api_port
    uvicorn.run(
        "transcriber_shell.api.app:app",
        host=host,
        port=port,
        reload=args.reload,
    )
    return 0


def cmd_yaml_to_tei(args: argparse.Namespace) -> int:
    from transcriber_shell.xml_tools.tei import yaml_to_tei, convert_dir

    if args.dir:
        out_dir = Path(args.out_dir) if args.out_dir else Path(args.dir).parent / "tei"
        pairs = convert_dir(Path(args.dir), out_dir)
        for src, dst in pairs:
            print(f"  {src.name} → {dst.name}")
        print(f"  {len(pairs)} file(s) converted")
        return 0 if pairs else 1
    if args.input:
        src = Path(args.input)
        dst = Path(args.output) if args.output else src.with_suffix(".tei.xml")
        yaml_to_tei(src, dst)
        print(f"  {src.name} → {dst.name}")
        return 0
    print("error: provide --dir or a file argument", file=sys.stderr)
    return 1


def cmd_score(args: argparse.Namespace) -> int:
    from transcriber_shell.pipeline.score import score_expanded_vs_gt

    expanded_dir = Path(args.expanded_dir).expanduser().resolve()
    settings = Settings()
    gt_dir = Path(args.gt).expanduser().resolve() if args.gt else (
        settings.gt_dir.expanduser().resolve() if settings.gt_dir else None
    )
    if not gt_dir:
        print("error: --gt required (or set TRANSCRIBER_SHELL_GT_DIR / LATIN_MS_GT_DIR)", file=sys.stderr)
        return 1
    if not expanded_dir.is_dir():
        print(f"error: {expanded_dir} is not a directory", file=sys.stderr)
        return 1

    report = score_expanded_vs_gt(expanded_dir, gt_dir, verbose=not args.quiet)
    if not report.cases:
        print("No scoreable cases found.", file=sys.stderr)
        return 1

    agg = report.to_dict()["aggregate"]
    print(f"\n{'─'*64}")
    print(f"  AGGREGATE ({agg['n']} cases):  CER {agg['cer']:.2f}%   WER {agg['wer']:.2f}%   [{agg['disposition']}]")
    print(f"{'─'*64}")

    if args.report:
        report.write(Path(args.report).expanduser())
        print(f"  reports: {args.report}/score_report.{{json,txt}}")
    if args.json:
        import json
        print(json.dumps(report.to_dict(), indent=2))
    return 0


def cmd_convert_images(args: argparse.Namespace) -> int:
    from transcriber_shell.image_tools.convert import find_images, convert_file

    sources = [Path(s) for s in args.sources]
    images = find_images(sources, recurse=args.recurse)
    if not images:
        print("No images found.", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None
    fmt = args.format
    print(f"==> convert-images: {len(images)} image(s) → {fmt.upper()}"
          + ("  [DRY RUN]" if args.dry_run else ""))

    counts: dict[str, int] = {"converted": 0, "skipped": 0, "error": 0, "dry-run": 0}
    for src in images:
        status, msg = convert_file(
            src,
            out_dir=out_dir,
            fmt=fmt,
            max_width=args.max_width,
            max_height=args.max_height,
            quality=args.quality,
            keep_original=args.keep_original,
            force=args.force,
            dry_run=args.dry_run,
            scale_xml=not args.no_scale_xml,
        )
        counts[status] = counts.get(status, 0) + 1
        prefix = {"converted": "  ✓", "skipped": "  –", "error": "  ✗", "dry-run": "  ?"}[status]
        print(f"{prefix} {msg}")

    verb = "Would convert" if args.dry_run else "Converted"
    key = "dry-run" if args.dry_run else "converted"
    print(f"\n  {verb} {counts[key]}, skipped {counts['skipped']}, errors {counts['error']}")
    return 1 if counts["error"] else 0


def cmd_mask_illustrations(args: argparse.Namespace) -> int:
    from transcriber_shell.image_tools.mask import load_model, mask_file
    from transcriber_shell.image_tools.convert import find_images

    settings = Settings()
    model_path = Path(args.model).expanduser() if args.model else (
        settings.eynollah_model_path or Path.home() / "eynollah_models" / "extract_images"
    )
    if not model_path.exists():
        print(f"error: eynollah model not found at {model_path}", file=sys.stderr)
        return 1

    sources = [Path(s) for s in args.sources]
    images = find_images(sources, recurse=args.recurse)
    if not images:
        print("No images found.", file=sys.stderr)
        return 1

    classes = [int(c.strip()) for c in args.classes.split(",")]
    dilate_px = args.dilate if args.dilate is not None else settings.mask_dilate_px
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None
    suffix = args.suffix if not args.in_place else ""

    print(f"==> mask-illustrations: {len(images)} image(s)  classes={classes}  dilate={dilate_px}px")
    if not args.dry_run:
        print("  Loading model...", flush=True)
        infer = load_model(model_path)
        print("  Ready.")

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    ok = err = 0
    for src in images:
        if args.dry_run:
            print(f"  ? {src.name}")
            ok += 1
            continue
        status, msg = mask_file(
            src, infer,
            out_dir=out_dir,
            suffix=suffix,
            in_place=args.in_place,
            classes=classes,
            dilate_px=dilate_px,
        )
        print(f"  {'✓' if status == 'ok' else '✗'} {msg}")
        if status == "ok":
            ok += 1
        else:
            err += 1

    print(f"\n  Processed {ok}, errors {err}")
    return 1 if err else 0


def cmd_list_doc_types(_args: argparse.Namespace) -> int:
    from transcriber_shell.document_types import list_doc_types
    settings = Settings()
    extra = [settings.document_types_dir] if settings.document_types_dir else []
    names = list_doc_types(extra)
    if not names:
        print("No document type specs found.", file=sys.stderr)
        return 1
    for name in names:
        print(f"  {name}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="transcriber-shell",
        description=(
            "Manuscript transcription: lines XML (Glyph Machina by default) → LLM → protocol YAML. "
            "Start with: transcriber-shell gui   or   transcriber-shell run --job-id ID --image PATH --prompt PATH"
        ),
        epilog="Minimal path: docs/simple-workflow.md  ·  Full setup: docs/local-setup.md",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    th = sub.add_parser(
        "test-htr",
        help=(
            "Evaluate a Kraken HTR model against ground truth. "
            "PAGE/ALTO XML → transcription + optional baseline accuracy. "
            "PNG+.gt.txt pairs → transcription accuracy only."
        ),
    )
    th.add_argument(
        "--model", "-m", required=True,
        help="Kraken HTR model (.mlmodel or .safetensors)",
    )
    th.add_argument(
        "--gt", "-g", required=True,
        help="Ground-truth directory or file (PAGE XML, ALTO XML, or PNG+.gt.txt)",
    )
    th.add_argument(
        "--seg-model", "-s", default=None,
        help="Kraken segmentation model for baseline accuracy (XML ground truth only)",
    )
    th.add_argument(
        "--device", "-d", default="cpu",
        help="Device for ketos/kraken (e.g. cpu, cuda:0) [default: cpu]",
    )
    th.add_argument(
        "--centroid-match-px", type=float, default=120.0,
        help="Max centroid distance to pair baselines (default: 120)",
    )
    th.add_argument(
        "--json", action="store_true",
        help="Print JSON report",
    )
    th.set_defaults(func=cmd_test_htr)

    cmp = sub.add_parser(
        "compare-lines-xml",
        help="Compare hypothesis lines XML to reference (e.g. Glyph Machina = ground truth)",
    )
    cmp.add_argument(
        "--reference",
        "-r",
        required=True,
        help="Reference PageXML (e.g. Glyph Machina download)",
    )
    cmp.add_argument(
        "--hypothesis",
        "-y",
        required=True,
        help="Hypothesis PageXML (e.g. local mask / Kraken)",
    )
    cmp.add_argument(
        "--centroid-match-px",
        type=float,
        default=120.0,
        help="Max centroid distance to pair lines (default: 120)",
    )
    cmp.add_argument(
        "--json",
        action="store_true",
        help="Print JSON report",
    )
    cmp.set_defaults(func=cmd_compare_lines_xml)

    vx = sub.add_parser("validate-xml", help="Check PageXML / lines file (optional XSD)")
    vx.add_argument("file")
    vx.add_argument(
        "--require-text-line",
        action="store_true",
        help="Require at least one TextLine element",
    )
    vx.add_argument("--xsd", metavar="PATH", help="Optional PAGE XML XSD path (needs lxml)")
    vx.set_defaults(func=cmd_validate_xml)

    vg = sub.add_parser(
        "validate-gt-pagexml",
        help="Validate human PAGE XML vs image size and baselines (ground truth QA)",
    )
    vg.add_argument("xml", type=Path, help="PAGE XML file")
    vg.add_argument("image", type=Path, help="Matching image file")
    vg.set_defaults(func=cmd_validate_gt_pagexml_cli)

    vy = sub.add_parser("validate-yaml", help="Validate transcriptionOutput YAML/JSON")
    vy.add_argument("file")
    vy.set_defaults(func=cmd_validate_yaml)

    run = sub.add_parser(
        "run",
        help="Full pipeline: lineation (Glyph Machina default · mask · Kraken) → LLM → validate",
    )
    run.add_argument("--job-id", required=True)
    run.add_argument("--image", required=True, help="Pre-cropped image path")
    run.add_argument(
        "--prompt",
        default=None,
        help="JSON or YAML file with prompt config (prompt-templates CONFIGURATION keys); optional when --doc-type is set",
    )
    run.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "openai", "gemini", "ollama"],
        help="LLM provider (default: TRANSCRIBER_SHELL_DEFAULT_PROVIDER or anthropic)",
    )
    run.add_argument(
        "--model",
        default=None,
        help="Override model id (overrides TRANSCRIBER_SHELL_MODEL and per-provider defaults)",
    )
    run.add_argument(
        "--skip-gm",
        action="store_true",
        help="Skip automated lineation; use --lines-xml from disk",
    )
    run.add_argument(
        "--lineation-backend",
        dest="lineation_backend",
        default=None,
        choices=["mask", "kraken", "glyph_machina"],
        help="Lineation source (default: env or glyph_machina). Ignored with --skip-gm.",
    )
    run.add_argument("--lines-xml", help="Existing lines XML when using --skip-gm")
    run.add_argument(
        "--xsd",
        help="Optional XSD for lines XML (overrides TRANSCRIBER_SHELL_LINES_XML_XSD if set)",
    )
    run.add_argument(
        "--no-require-text-line",
        action="store_true",
        help="Do not fail XML step when TextLine count is 0",
    )
    run.add_argument(
        "--skip-successful",
        action="store_true",
        help="Skip run when artifacts/<job_id>/<image_stem>_transcription.yaml already validates",
    )
    run.add_argument(
        "--skip-lines-xml-validation",
        action="store_true",
        help="Skip lines XML checks and optional PAGE XSD; still run LLM (env: TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION)",
    )
    run.add_argument(
        "--doc-type",
        dest="doc_type",
        default=None,
        metavar="NAME",
        help=(
            "Document type name (e.g. medieval_latin_legal). "
            "Loads matching spec YAML to set prompt, HTR model, seg model, and provider defaults. "
            "CLI args override spec values. (env: TRANSCRIBER_SHELL_DOC_TYPE)"
        ),
    )
    run.add_argument(
        "--continue-on-lineation-failure",
        action="store_true",
        help=(
            "If automated lineation fails, continue to LLM without lines XML "
            "(env: TRANSCRIBER_SHELL_CONTINUE_ON_LINEATION_FAILURE)"
        ),
    )
    run.add_argument(
        "--htr-sequential",
        action="store_true",
        dest="htr_sequential",
        help=(
            "Run kraken-htr / gm-htr before the LLM and attach drafts to the lineation hint "
            "(lineation → HTR → LLM). Default is HTR in parallel with the LLM (env: TRANSCRIBER_SHELL_HTR_PARALLEL=false). "
            "Ignored if --htr-combination is set."
        ),
    )
    run.add_argument(
        "--htr-combination",
        dest="htr_combination",
        default=None,
        choices=[
            "default",
            "off",
            "shell",
            "kraken_htr",
            "gm_htr",
            "parallel",
            "sequential",
            "gm_then_kraken",
            "kraken_then_gm",
        ],
        help=(
            "Glyph Machina HTR + Zenodo kraken-htr + LLM shell: shell=LLM only; kraken_htr|gm_htr=one backend; "
            "parallel|sequential=all configured; gm_then_kraken|kraken_then_gm=ordered before LLM. "
            "Overrides --htr-sequential when set (env: TRANSCRIBER_SHELL_HTR_COMBINATION)."
        ),
    )
    run.add_argument(
        "--xml-only",
        action="store_true",
        help=(
            "Lineation and lines XML validation only; do not call the LLM "
            "(env: TRANSCRIBER_SHELL_XML_ONLY)"
        ),
    )
    run_dipl = run.add_mutually_exclusive_group()
    run_dipl.add_argument(
        "--diplomatic",
        dest="diplomatic",
        action="store_const",
        const=True,
        default=None,
        help="Override normalizationMode=diplomatic in the prompt config (protocol default).",
    )
    run_dipl.add_argument(
        "--no-diplomatic",
        dest="diplomatic",
        action="store_const",
        const=False,
        help="Override normalizationMode=normalized in the prompt config.",
    )
    _add_pipeline_network_args(run)
    run.set_defaults(func=cmd_run)

    batch = sub.add_parser(
        "batch",
        help="Run pipeline for every image in a directory or glob",
    )
    batch.add_argument(
        "path",
        help="Directory of images, a single image file, or a glob (e.g. 'scans/*.jpg')",
    )
    batch.add_argument(
        "--prompt",
        default=None,
        help="JSON or YAML file with prompt config; optional when --doc-type is set",
    )
    batch.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "openai", "gemini", "ollama"],
        help="LLM provider (default: TRANSCRIBER_SHELL_DEFAULT_PROVIDER or anthropic)",
    )
    batch.add_argument("--model", default=None, help="Override model id for every job")
    batch.add_argument("--skip-gm", action="store_true")
    batch.add_argument(
        "--lineation-backend",
        dest="lineation_backend",
        default=None,
        choices=["mask", "kraken", "glyph_machina"],
        help="Lineation source when not using --skip-gm (default: env or glyph_machina)",
    )
    batch.add_argument(
        "--lines-xml",
        help="Single lines XML (only when batch has exactly one image)",
    )
    batch.add_argument(
        "--lines-xml-dir",
        help="Directory of <stem>.xml files matching each image stem (for --skip-gm)",
    )
    batch.add_argument(
        "--xsd",
        help="Optional XSD for lines XML (overrides TRANSCRIBER_SHELL_LINES_XML_XSD if set)",
    )
    batch.add_argument("--no-require-text-line", action="store_true")
    batch.add_argument(
        "--skip-successful",
        action="store_true",
        help="Skip images with existing valid artifacts/<job_id>/<image_stem>_transcription.yaml",
    )
    batch.add_argument(
        "--skip-lines-xml-validation",
        action="store_true",
        help="Skip lines XML checks and optional PAGE XSD; still run LLM (env: TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION)",
    )
    batch.add_argument(
        "--doc-type",
        dest="doc_type",
        default=None,
        metavar="NAME",
        help=(
            "Document type name (e.g. medieval_latin_legal). "
            "Sets prompt, HTR model, seg model, and provider from spec YAML. "
            "CLI args override. (env: TRANSCRIBER_SHELL_DOC_TYPE)"
        ),
    )
    batch.add_argument(
        "--continue-on-lineation-failure",
        action="store_true",
        help=(
            "If automated lineation fails, continue to LLM without lines XML "
            "(env: TRANSCRIBER_SHELL_CONTINUE_ON_LINEATION_FAILURE)"
        ),
    )
    batch.add_argument(
        "--htr-sequential",
        action="store_true",
        dest="htr_sequential",
        help=(
            "Run kraken-htr / gm-htr before the LLM and attach drafts to the lineation hint "
            "(lineation → HTR → LLM). Default is HTR in parallel with the LLM (env: TRANSCRIBER_SHELL_HTR_PARALLEL=false). "
            "Ignored if --htr-combination is set."
        ),
    )
    batch.add_argument(
        "--htr-combination",
        dest="htr_combination",
        default=None,
        choices=[
            "default",
            "off",
            "shell",
            "kraken_htr",
            "gm_htr",
            "parallel",
            "sequential",
            "gm_then_kraken",
            "kraken_then_gm",
        ],
        help=(
            "Glyph Machina HTR + Zenodo kraken-htr + LLM shell: shell=LLM only; kraken_htr|gm_htr=one backend; "
            "parallel|sequential=all configured; gm_then_kraken|kraken_then_gm=ordered before LLM. "
            "Overrides --htr-sequential when set (env: TRANSCRIBER_SHELL_HTR_COMBINATION)."
        ),
    )
    batch.add_argument(
        "--xml-only",
        action="store_true",
        help=(
            "Lineation and lines XML validation only; do not call the LLM "
            "(env: TRANSCRIBER_SHELL_XML_ONLY)"
        ),
    )
    batch.add_argument(
        "--batch-report",
        metavar="PATH",
        help="Write JSON report of all jobs",
    )
    batch_dipl = batch.add_mutually_exclusive_group()
    batch_dipl.add_argument(
        "--diplomatic",
        dest="diplomatic",
        action="store_const",
        const=True,
        default=None,
        help="Override normalizationMode=diplomatic in the prompt config (protocol default).",
    )
    batch_dipl.add_argument(
        "--no-diplomatic",
        dest="diplomatic",
        action="store_const",
        const=False,
        help="Override normalizationMode=normalized in the prompt config.",
    )
    _add_pipeline_network_args(batch)
    batch.set_defaults(func=cmd_batch)

    gui = sub.add_parser(
        "gui",
        help="Desktop UI (tkinter): images, prompt, lineation backend (Glyph Machina default · mask/Kraken) or skip to lines XML",
    )
    gui.set_defaults(func=cmd_gui)

    serve = sub.add_parser("serve", help="Start optional HTTP API (requires [api] extra)")
    serve.add_argument("--host", default=None, help="Bind host (default: env or 127.0.0.1)")
    serve.add_argument("--port", type=int, default=None, help="Port (default: env or 8765)")
    serve.add_argument(
        "--reload",
        action="store_true",
        help="Uvicorn auto-reload (development)",
    )
    serve.set_defaults(func=cmd_serve)

    # ── yaml-to-tei ──────────────────────────────────────────────────────────
    ytt = sub.add_parser("yaml-to-tei", help="Convert protocol YAML transcription(s) to TEI XML")
    ytt.add_argument("input", nargs="?", help="Single *_transcription.yaml file")
    ytt.add_argument("output", nargs="?", help="Output .tei.xml path (single-file mode)")
    ytt.add_argument("--dir", metavar="PATH", help="Batch: directory of *_transcription.yaml files")
    ytt.add_argument("--out-dir", metavar="PATH", help="Output directory (batch mode)")
    ytt.set_defaults(func=cmd_yaml_to_tei)

    # ── score ────────────────────────────────────────────────────────────────
    sc = sub.add_parser(
        "score",
        help="CER/WER: score *_tei_expanded.xml output against PAGE XML ground truth",
    )
    sc.add_argument("expanded_dir", help="Directory of *_tei_expanded.xml files (04_expanded/out/)")
    sc.add_argument(
        "--gt", metavar="PATH", default=None,
        help="Ground-truth PAGE XML directory (env: TRANSCRIBER_SHELL_GT_DIR / LATIN_MS_GT_DIR)",
    )
    sc.add_argument(
        "--report", metavar="DIR", default=None,
        help="Write score_report.{json,txt} to this directory",
    )
    sc.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    sc.add_argument("--quiet", action="store_true", help="Suppress per-file output")
    sc.set_defaults(func=cmd_score)

    # ── convert-images ───────────────────────────────────────────────────────
    ci = sub.add_parser(
        "convert-images",
        help="Convert TIF/BMP/WebP/etc. to JPEG/PNG with optional PAGE XML coordinate scaling",
    )
    ci.add_argument("sources", nargs="+", help="Files or directories to convert")
    ci.add_argument("--out-dir", metavar="PATH", default=None)
    ci.add_argument("--format", choices=["jpeg", "png"], default="jpeg")
    ci.add_argument("--max-width", type=int, default=3000, metavar="PX")
    ci.add_argument("--max-height", type=int, default=None, metavar="PX")
    ci.add_argument("--quality", type=int, default=90)
    ci.add_argument("--keep-original", action="store_true")
    ci.add_argument("--force", action="store_true")
    ci.add_argument("--dry-run", action="store_true")
    ci.add_argument("--recurse", action="store_true")
    ci.add_argument("--no-scale-xml", action="store_true",
                    help="Skip automatic PAGE XML coordinate scaling when image is resized")
    ci.set_defaults(func=cmd_convert_images)

    # ── mask-illustrations ───────────────────────────────────────────────────
    mi = sub.add_parser(
        "mask-illustrations",
        help="White out illustration pixels (eynollah class 2) before lineation",
    )
    mi.add_argument("sources", nargs="+", help="Images or directories to process")
    mi.add_argument("--model", metavar="PATH", default=None,
                    help="eynollah SavedModel directory (env: TRANSCRIBER_SHELL_EYNOLLAH_MODEL)")
    mi.add_argument("--out-dir", metavar="PATH", default=None)
    mi.add_argument("--suffix", default="_masked",
                    help="Output filename suffix (default: _masked). Ignored with --in-place.")
    mi.add_argument("--in-place", action="store_true", help="Overwrite source files")
    mi.add_argument("--classes", default="2",
                    help="Comma-separated segmentation class indices to mask (default: 2)")
    mi.add_argument("--dilate", type=int, default=None, metavar="PX",
                    help="Dilation radius in pixels (env: TRANSCRIBER_SHELL_MASK_DILATE, default: 8)")
    mi.add_argument("--recurse", action="store_true")
    mi.add_argument("--dry-run", action="store_true")
    mi.set_defaults(func=cmd_mask_illustrations)

    # ── list-doc-types ───────────────────────────────────────────────────────
    ldt = sub.add_parser("list-doc-types", help="List available document type specs")
    ldt.set_defaults(func=cmd_list_doc_types)

    args = ap.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
