"""CLI: transcriber-shell."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.llm.validate_output import validate_transcript_file
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.batch import (
    discover_images,
    run_batch,
    write_batch_report,
)
from transcriber_shell.pipeline.run import load_prompt_cfg, run_pipeline
from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional


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


def cmd_run(args: argparse.Namespace) -> int:
    settings = Settings()
    cfg = load_prompt_cfg(Path(args.prompt))
    provider = _resolve_provider(args.provider, settings)
    job = TranscribeJob(
        job_id=args.job_id,
        image_path=Path(args.image),
        prompt_cfg=cfg,
        provider=provider,
        model_override=args.model,
    )
    lines_xml = Path(args.lines_xml).resolve() if args.lines_xml else None
    xsd = Path(args.xsd).resolve() if args.xsd else None
    res = run_pipeline(
        job,
        skip_gm=args.skip_gm,
        lines_xml_path=lines_xml,
        xsd_path=xsd,
        require_text_line=not args.no_require_text_line,
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
    settings = Settings()
    images = discover_images(args.path)
    if not images:
        print("No images found (supported: .jpg, .jpeg, .png, .webp, …)", file=sys.stderr)
        return 2
    cfg = load_prompt_cfg(Path(args.prompt))
    provider = _resolve_provider(args.provider, settings)
    lines_xml = Path(args.lines_xml).resolve() if args.lines_xml else None
    lines_xml_dir = Path(args.lines_xml_dir).resolve() if args.lines_xml_dir else None
    xsd = Path(args.xsd).resolve() if args.xsd else None
    rows = run_batch(
        images,
        cfg,
        provider=provider,
        model_override=args.model,
        skip_gm=args.skip_gm,
        lines_xml=lines_xml,
        lines_xml_dir=lines_xml_dir,
        xsd_path=xsd,
        require_text_line=not args.no_require_text_line,
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


def main() -> None:
    ap = argparse.ArgumentParser(prog="transcriber-shell")
    sub = ap.add_subparsers(dest="cmd", required=True)

    vx = sub.add_parser("validate-xml", help="Check PageXML / lines file (optional XSD)")
    vx.add_argument("file")
    vx.add_argument(
        "--require-text-line",
        action="store_true",
        help="Require at least one TextLine element",
    )
    vx.add_argument("--xsd", metavar="PATH", help="Optional PAGE XML XSD path (needs lxml)")
    vx.set_defaults(func=cmd_validate_xml)

    vy = sub.add_parser("validate-yaml", help="Validate transcriptionOutput YAML/JSON")
    vy.add_argument("file")
    vy.set_defaults(func=cmd_validate_yaml)

    run = sub.add_parser("run", help="Full pipeline: Glyph Machina → LLM → validate")
    run.add_argument("--job-id", required=True)
    run.add_argument("--image", required=True, help="Pre-cropped image path")
    run.add_argument(
        "--prompt",
        required=True,
        help="JSON or YAML file with prompt config (prompt-templates CONFIGURATION keys)",
    )
    run.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "openai", "gemini"],
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
        help="Skip browser automation; use --lines-xml from disk",
    )
    run.add_argument("--lines-xml", help="Existing lines XML when using --skip-gm")
    run.add_argument("--xsd", help="Optional XSD for lines XML")
    run.add_argument(
        "--no-require-text-line",
        action="store_true",
        help="Do not fail XML step when TextLine count is 0",
    )
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
        required=True,
        help="JSON or YAML file with prompt config",
    )
    batch.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "openai", "gemini"],
        help="LLM provider (default: TRANSCRIBER_SHELL_DEFAULT_PROVIDER or anthropic)",
    )
    batch.add_argument("--model", default=None, help="Override model id for every job")
    batch.add_argument("--skip-gm", action="store_true")
    batch.add_argument(
        "--lines-xml",
        help="Single lines XML (only when batch has exactly one image)",
    )
    batch.add_argument(
        "--lines-xml-dir",
        help="Directory of <stem>.xml files matching each image stem (for --skip-gm)",
    )
    batch.add_argument("--xsd", help="Optional XSD for lines XML")
    batch.add_argument("--no-require-text-line", action="store_true")
    batch.add_argument(
        "--batch-report",
        metavar="PATH",
        help="Write JSON report of all jobs",
    )
    batch.set_defaults(func=cmd_batch)

    serve = sub.add_parser("serve", help="Start optional HTTP API (requires [api] extra)")
    serve.add_argument("--host", default=None, help="Bind host (default: env or 127.0.0.1)")
    serve.add_argument("--port", type=int, default=None, help="Port (default: env or 8765)")
    serve.add_argument(
        "--reload",
        action="store_true",
        help="Uvicorn auto-reload (development)",
    )
    serve.set_defaults(func=cmd_serve)

    args = ap.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
