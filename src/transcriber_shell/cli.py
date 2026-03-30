"""CLI: transcriber-shell."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.llm.validate_output import validate_transcript_file
from transcriber_shell.models.job import TranscribeJob
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


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_prompt_cfg(Path(args.prompt))
    job = TranscribeJob(
        job_id=args.job_id,
        image_path=Path(args.image),
        prompt_cfg=cfg,
        provider=args.provider,
    )
    lines_xml = Path(args.lines_xml).resolve() if args.lines_xml else None
    xsd = Path(args.xsd).resolve() if args.xsd else None
    res = run_pipeline(
        job,
        skip_gm=args.skip_gm,
        lines_xml_path=lines_xml,
        xsd_path=xsd,
        require_text_line=not args.no_require_text_line,
        settings=Settings(),
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
    run.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "gemini"])
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

    args = ap.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
