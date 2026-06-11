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
from transcriber_shell.pipeline.run import (
    load_prompt_cfg,
    run_pipeline,
    set_normalization_mode_for_diplomatic,
)
from transcriber_shell.pipeline.transcription_paths import transcription_yaml_path
from transcriber_shell.xml_tools.lines_compare import compare_lines_xml, format_comparison_report
from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
from transcriber_shell.xml_tools.validate_gt_pagexml import validate_gt_pagexml
from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional


# ── doc-type helpers ─────────────────────────────────────────────────────────

def _apply_htr_model_override(name: str | None, settings: Settings) -> Settings:
    """If ``name`` is given, resolve it through the model registry and override
    ``settings.kraken_htr_model_path``. The override always wins over the env
    var and any doc-type default.
    """
    if not name:
        return settings
    from transcriber_shell.htr import model_registry

    spec = model_registry.by_name(name.strip())
    if spec is None:
        print(
            f"error: --htr-model {name!r} not found in registry. "
            f"Run `transcriber-shell list-htr-models` to see available names.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not spec.exists:
        print(
            f"error: --htr-model {name!r} found in registry but file missing on disk: {spec.path}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return settings.model_copy(update={"kraken_htr_model_path": spec.path})


def cmd_list_htr_models(_args: argparse.Namespace) -> int:
    """Print the model registry as a table."""
    from transcriber_shell.htr import model_registry

    print(model_registry.format_table(model_registry.load_all()), end="")
    return 0


def cmd_score_htr_per_corpus(args: argparse.Namespace) -> int:
    """Run ``test-htr`` against each subdirectory under EVAL_DIR and report per-corpus CER.

    Layout expected::

        EVAL_DIR/
            catmus-medieval/   <- per-corpus subdir, PAGE/ALTO XML or PNG+.gt.txt
            tridis/
            posner-em-latin/
            …

    Optionally writes the resulting per_corpus_cer dict back into the model's
    registry YAML so the next ``list-htr-models`` shows fresh metrics.
    """
    import json
    from transcriber_shell.htr.eval import evaluate, format_eval_report
    from transcriber_shell.htr import model_registry

    model_arg = args.model
    if not model_arg:
        print("error: --model NAME (registry name) or --model-path PATH is required", file=sys.stderr)
        return 1

    if args.model_path:
        model_path = Path(args.model_path).expanduser().resolve()
        registry_spec = None
    else:
        registry_spec = model_registry.by_name(model_arg)
        if registry_spec is None:
            print(f"error: model {model_arg!r} not in registry", file=sys.stderr)
            return 1
        if not registry_spec.exists:
            print(f"error: model {model_arg!r} registry entry's path missing on disk: {registry_spec.path}", file=sys.stderr)
            return 1
        model_path = registry_spec.path

    eval_root = Path(args.eval_dir).expanduser().resolve()
    if not eval_root.is_dir():
        print(f"error: --eval-dir not a directory: {eval_root}", file=sys.stderr)
        return 1

    seg_model = Path(args.seg_model).expanduser().resolve() if args.seg_model else None
    device = args.device

    corpora = sorted([p for p in eval_root.iterdir() if p.is_dir()])
    if not corpora:
        print(f"error: no corpus subdirectories under {eval_root}", file=sys.stderr)
        return 1

    per_corpus: dict[str, float | None] = {}
    print(f"model: {model_path}")
    print(f"eval root: {eval_root}")
    print(f"corpora: {[p.name for p in corpora]}")
    print()
    for corpus_dir in corpora:
        print(f"── {corpus_dir.name} ──")
        try:
            result = evaluate(
                model_path,
                corpus_dir,
                seg_model=seg_model,
                device=device,
                centroid_match_px=args.centroid_match_px,
            )
        except (FileNotFoundError, RuntimeError) as e:
            print(f"  skipped: {e}")
            per_corpus[corpus_dir.name] = None
            continue
        if result.transcription is None:
            print("  no transcription metrics produced")
            per_corpus[corpus_dir.name] = None
            continue
        cer = result.transcription.cer()
        per_corpus[corpus_dir.name] = round(cer, 6)
        print(format_eval_report(result, as_json=False), end="")

    print()
    print("=== per-corpus CER ===")
    width = max((len(k) for k in per_corpus), default=8)
    for k, v in per_corpus.items():
        s = f"{v:.4f}" if isinstance(v, float) else "—"
        print(f"  {k:<{width}}  {s}")

    if args.json:
        print()
        print(json.dumps(per_corpus, indent=2))

    if args.update_registry and registry_spec is not None:
        import yaml
        raw = yaml.safe_load(registry_spec.source_path.read_text(encoding="utf-8")) or {}
        metrics = raw.setdefault("metrics", {})
        existing = metrics.get("per_corpus_cer") or {}
        existing.update({k: v for k, v in per_corpus.items() if v is not None})
        metrics["per_corpus_cer"] = existing
        registry_spec.source_path.write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print()
        print(f"updated metrics.per_corpus_cer in {registry_spec.source_path}")

    return 0


def _apply_doc_type(
    doc_type: str | None,
    settings: Settings,
    prompt_arg: str | None,
) -> tuple[Settings, str | None]:
    """Load doc-type spec and apply it to settings + prompt path."""
    if not doc_type:
        return settings, prompt_arg

    from transcriber_shell.doc_type_apply import apply_doc_type

    try:
        return apply_doc_type(doc_type, settings, prompt_arg)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)


def _auto_doc_type_for_image(
    image: Path,
    library_path: Path,
    *,
    lines_xml_dir: Path | None,
    min_similarity: float,
    top_k: int,
) -> tuple[str | None, list[dict]]:
    """Return (suggested_doc_type, top_matches) for an image via fingerprint match.

    Resolves the lines XML in `lines_xml_dir/<stem>.xml`, or falls back to the
    canonical `<image.parent.parent>/02_lines/<stem>.xml`.
    """
    from manuscript_fingerprint import (
        extract_doc_heights,
        build_fingerprint,
        suggest_doc_type,
        load_fingerprint_json,
    )

    if lines_xml_dir is not None:
        xml = lines_xml_dir / f"{image.stem}.xml"
    else:
        xml = image.parent.parent / "02_lines" / f"{image.stem}.xml"
    if not xml.is_file():
        raise FileNotFoundError(f"lines XML not found for {image.name}: {xml}")

    library = load_fingerprint_json(library_path)
    heights, n_lines, n_seen = extract_doc_heights(image, xml)
    target = build_fingerprint(heights, image.stem, n_lines=n_lines, n_components=n_seen)
    result = suggest_doc_type(target, library, top_k=top_k, min_similarity=min_similarity)
    return result.get("suggested_doc_type"), result.get("matches", [])


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

    doc_type = getattr(args, "doc_type", None)
    auto_lib = getattr(args, "auto_doc_type", None)
    if auto_lib and not doc_type:
        try:
            xml_dir = _expand_resolve_cli_path(getattr(args, "lines_xml_dir", None))
            suggested, matches = _auto_doc_type_for_image(
                Path(args.image), Path(auto_lib).expanduser().resolve(),
                lines_xml_dir=xml_dir,
                min_similarity=getattr(args, "auto_min_similarity", 0.5),
                top_k=3,
            )
        except FileNotFoundError as e:
            print(f"error: --auto-doc-type: {e}", file=sys.stderr)
            return 1
        if suggested:
            doc_type = suggested
            top = matches[0] if matches else {}
            print(f"auto-doc-type: {suggested} (best match: {top.get('b','?')}, "
                  f"similarity={top.get('similarity','?')})", file=sys.stderr)
        else:
            print(f"auto-doc-type: no confident match above {getattr(args,'auto_min_similarity',0.5)}; "
                  f"proceeding without doc-type", file=sys.stderr)

    settings, prompt_path = _apply_doc_type(
        doc_type, settings, getattr(args, "prompt", None)
    )
    settings = _apply_htr_model_override(getattr(args, "htr_model", None), settings)
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
    def _cli_log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    res = run_pipeline(
        job,
        skip_gm=args.skip_gm,
        lines_xml_path=lines_xml,
        xsd_path=xsd,
        require_text_line=_require_text_line_from_cli(args, settings),
        skip_lines_xml_validation=_skip_lines_xml_validation_from_cli(args, settings),
        settings=settings,
        log_fn=_cli_log,
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
    if getattr(args, "extract_figures", False) and res.transcription_yaml_path:
        _cli_extract_figures(
            yaml_path=res.transcription_yaml_path,
            image_path=Path(args.image),
            lines_xml_path=res.lines_xml_path,
            settings=settings,
        )
    if getattr(args, "translate", False) and res.transcription_yaml_path:
        _cli_translate(
            yaml_path=res.transcription_yaml_path,
            image_path=Path(args.image),
            provider=provider,
            model=args.model,
            settings=settings,
        )
    return 0


def _cli_extract_figures(
    *,
    yaml_path: Path,
    image_path: Path,
    lines_xml_path: Path | None,
    settings: Settings,
) -> None:
    """Best-effort figure extraction pass for CLI --extract-figures."""
    try:
        from transcriber_shell.pipeline.figure_extract import extract_figures_for_page

        s = settings.model_copy(update={"figure_extract_enabled": True})
        report = extract_figures_for_page(
            image_path=image_path,
            lines_xml_path=lines_xml_path,
            transcription_yaml_path=yaml_path,
            settings=s,
        )
        for w in report.warnings:
            print(f"figures warning: {w}", file=sys.stderr)
        if not report.figures:
            print("figures: none detected")
            return
        crops_dir = yaml_path.parent / "figures"
        print(f"figures_detected={len(report.figures)}  crops_dir={crops_dir}")
        for f in report.figures:
            print(f"  {f.id}  {f.label}  conf={f.confidence:.2f}  bbox={f.bbox}")
    except Exception as e:  # noqa: BLE001 — best-effort
        print(f"figure extraction failed: {e}", file=sys.stderr)


def _cli_translate(
    *,
    yaml_path: Path,
    image_path: Path,
    provider: str,
    model: str | None,
    settings: Settings,
) -> None:
    """Best-effort translation pass for CLI --translate. Logs errors and returns."""
    try:
        from transcriber_shell.llm.translate import run_translate, translation_output_path
        from transcriber_shell.llm.validate_output import (
            load_yaml_or_json_path,
            load_transcription_root,
        )

        data = load_yaml_or_json_path(Path(yaml_path))
        root = load_transcription_root(data) if data else None
        segs = root.get("segments") if isinstance(root, dict) else None
        if not isinstance(segs, list) or not segs:
            print(f"translation: skipped (no segments in {yaml_path.name})", file=sys.stderr)
            return
        parts: list[str] = []
        for seg in segs:
            if isinstance(seg, dict):
                t = seg.get("text") or seg.get("transcription") or ""
                if isinstance(t, str):
                    parts.append(t)
        diplomatic = "\n".join(p for p in parts if p)
        if not diplomatic.strip():
            print(f"translation: skipped (empty diplomatic text)", file=sys.stderr)
            return
        result = run_translate(
            image_path=image_path,
            diplomatic_text=diplomatic,
            provider=provider,
            model=model,
            settings=settings,
        )
        out = translation_output_path(yaml_path)
        out.write_text(result.text + "\n", encoding="utf-8")
        print(f"translation_txt={out}")
    except Exception as e:  # noqa: BLE001 — best-effort
        print(f"translation failed: {e}", file=sys.stderr)


def cmd_batch(args: argparse.Namespace) -> int:
    base_settings = _pipeline_settings(args)
    if getattr(args, "lineation_backend", None):
        base_settings = base_settings.model_copy(
            update={"lineation_backend": args.lineation_backend}
        )

    images = discover_images(args.path)
    if not images:
        print("No images found (supported: .jpg, .jpeg, .png, .webp, …)", file=sys.stderr)
        return 2

    lines_xml = _expand_resolve_cli_path(args.lines_xml)
    lines_xml_dir = _expand_resolve_cli_path(args.lines_xml_dir)
    xsd = _resolve_xsd_path(args.xsd, base_settings)

    # Group images by suggested doc-type when --auto-doc-type is in effect.
    cli_doc_type = getattr(args, "doc_type", None)
    auto_lib = getattr(args, "auto_doc_type", None)
    if auto_lib and not cli_doc_type:
        lib_path = Path(auto_lib).expanduser().resolve()
        groups: dict[str | None, list[Path]] = {}
        for img in images:
            try:
                suggested, _ = _auto_doc_type_for_image(
                    img, lib_path,
                    lines_xml_dir=lines_xml_dir,
                    min_similarity=getattr(args, "auto_min_similarity", 0.5),
                    top_k=3,
                )
            except FileNotFoundError as e:
                print(f"  skip {img.name}: {e}", file=sys.stderr)
                groups.setdefault(None, []).append(img)
                continue
            groups.setdefault(suggested, []).append(img)
            print(f"  {img.name}: doc-type={suggested or '(none)'}", file=sys.stderr)
    else:
        groups = {cli_doc_type: list(images)}

    all_rows: list[dict] = []
    overall_ok = True
    for group_doc_type, group_images in groups.items():
        if not group_images:
            continue
        settings, prompt_path = _apply_doc_type(
            group_doc_type, base_settings, getattr(args, "prompt", None)
        )
        settings = _apply_htr_model_override(getattr(args, "htr_model", None), settings)
        if not prompt_path:
            print(
                f"error: --prompt is required (group doc-type={group_doc_type!r} has no prompt)",
                file=sys.stderr,
            )
            overall_ok = False
            continue
        cfg = load_prompt_cfg(Path(prompt_path))
        if getattr(args, "diplomatic", None) is not None:
            cfg["normalizationMode"] = "diplomatic" if args.diplomatic else "normalized"
        provider = _resolve_provider(args.provider, settings)
        if len(groups) > 1:
            print(f"\n== group doc-type={group_doc_type or '(none)'}, {len(group_images)} image(s) ==",
                  file=sys.stderr)
        def _cli_log(msg: str) -> None:
            print(msg, file=sys.stderr, flush=True)

        rows = run_batch(
            group_images,
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
            log_fn=_cli_log,
        )
        all_rows.extend(rows)
        if not all(r.get("ok") for r in rows):
            overall_ok = False
        if getattr(args, "extract_figures", False):
            for row in rows:
                if not row.get("ok") or row.get("skipped"):
                    continue
                yml = row.get("transcription_yaml")
                img = row.get("image")
                if yml and img:
                    _cli_extract_figures(
                        yaml_path=Path(yml),
                        image_path=Path(img),
                        lines_xml_path=Path(row["lines_xml"]) if row.get("lines_xml") else None,
                        settings=settings,
                    )
        if getattr(args, "translate", False):
            for row in rows:
                if not row.get("ok") or row.get("skipped"):
                    continue
                yml = row.get("transcription_yaml")
                img = row.get("image")
                if yml and img:
                    _cli_translate(
                        yaml_path=Path(yml),
                        image_path=Path(img),
                        provider=provider,
                        model=args.model,
                        settings=settings,
                    )
    rows = all_rows
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
            use_cucim=getattr(args, "use_cucim", False),
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


def _resolve_image_xml_pairs(job_dir: Path) -> list[tuple[Path, Path]]:
    pages_dir = job_dir / "01_pages"
    lines_dir = job_dir / "02_lines"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"{pages_dir} does not exist")
    if not lines_dir.is_dir():
        raise FileNotFoundError(f"{lines_dir} does not exist")
    image_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    pairs: list[tuple[Path, Path]] = []
    for img in sorted(pages_dir.iterdir()):
        if img.suffix.lower() not in image_exts:
            continue
        xml = lines_dir / f"{img.stem}.xml"
        if not xml.is_file():
            print(f"  skip {img.name}: no matching {xml.name}", file=sys.stderr)
            continue
        pairs.append((img, xml))
    return pairs


def cmd_fingerprint(args: argparse.Namespace) -> int:
    import json
    from manuscript_fingerprint import (
        extract_doc_heights,
        build_fingerprint,
    )

    job_dir = Path(args.job_dir).expanduser().resolve()
    try:
        pairs = _resolve_image_xml_pairs(job_dir)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not pairs:
        print("error: no (image, xml) pairs found", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else (job_dir / "fingerprints.json")
    fps: list[dict] = []
    for img, xml in pairs:
        doc_id = img.stem
        print(f"  fingerprint {doc_id} ...", file=sys.stderr, flush=True)
        try:
            heights, n_lines, n_seen = extract_doc_heights(
                img, xml,
                min_height_px=args.min_height_px,
                max_height_px=args.max_height_px,
            )
        except Exception as e:
            print(f"    failed: {e}", file=sys.stderr)
            continue
        fp = build_fingerprint(
            heights, doc_id,
            n_lines=n_lines,
            n_components=n_seen,
            doc_type=args.doc_type,
        )
        fps.append(fp.to_dict())
        print(
            f"    n_lines={fp.n_lines} components={fp.n_components} kept={fp.n_components_kept} "
            f"mean={fp.height_mean} std={fp.height_std}",
            file=sys.stderr,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fps, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(fps)} fingerprints → {out_path}")
    return 0


def cmd_fingerprint_compare(args: argparse.Namespace) -> int:
    import json
    import math
    from manuscript_fingerprint import (
        compare,
        compare_batch,
        load_fingerprint_json,
    )

    fps_a = load_fingerprint_json(Path(args.a))
    fps_b = load_fingerprint_json(Path(args.b)) if args.b else None

    if fps_b is None:
        if len(fps_a) < 2:
            print("error: single-batch compare needs ≥2 fingerprints in A", file=sys.stderr)
            return 1
        matrix = compare_batch(fps_a)
        ids = [fp.doc_id for fp in fps_a]
        if args.json:
            print(json.dumps({"docs": ids, "matrix": matrix}, indent=2))
        else:
            col_w = max(14, max(len(i) for i in ids) + 2)
            print(" " * col_w + " ".join(f"{i:>10.10s}" for i in ids))
            for i, row in enumerate(matrix):
                cells = " ".join(("    inf  " if math.isinf(v) else f"{v:>10.3f}") for v in row)
                print(f"{ids[i]:<{col_w}.{col_w}s}{cells}")
        return 0

    results = []
    for a in fps_a:
        for b in fps_b:
            results.append(compare(a, b))
    results.sort(key=lambda r: r["combined_distance"])

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"{'A':<24} {'B':<24} {'script':>8} {'shape':>8} {'combined':>10} {'sim':>6}")
        for r in results:
            print(
                f"{r['a']:<24.24s} {r['b']:<24.24s} "
                f"{r['script_distance']:>8.3f} {r['shape_distance']:>8.3f} "
                f"{r['combined_distance']:>10.3f} {r['similarity']:>6.3f}"
            )
    return 0


def cmd_fingerprint_match(args: argparse.Namespace) -> int:
    """Compute fingerprint of a target doc and match against a library."""
    import json
    from manuscript_fingerprint import (
        extract_doc_heights,
        build_fingerprint,
        match_against_library,
        suggest_doc_type,
        load_fingerprint_json,
    )

    library = load_fingerprint_json(Path(args.library))
    if not library:
        print(f"error: library {args.library} is empty", file=sys.stderr)
        return 1

    img = Path(args.image).expanduser().resolve()
    xml = Path(args.lines_xml).expanduser().resolve() if args.lines_xml else \
        img.parent.parent / "02_lines" / f"{img.stem}.xml"
    if not xml.is_file():
        print(f"error: lines XML not found: {xml}", file=sys.stderr)
        return 1

    print(f"fingerprinting {img.name}...", file=sys.stderr)
    heights, n_lines, n_seen = extract_doc_heights(img, xml)
    target = build_fingerprint(heights, img.stem, n_lines=n_lines, n_components=n_seen)

    if args.suggest_doc_type:
        result = suggest_doc_type(target, library, top_k=args.top_k, min_similarity=args.min_similarity)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            sugg = result["suggested_doc_type"]
            print(f"\nsuggested doc-type: {sugg or '(none — no confident match)'}")
            if sugg:
                print(f"  vote_score: {result['vote_score']}")
            print(f"\ntop {len(result['matches'])} matches:")
            for m in result["matches"]:
                print(f"  {m['b']:<28.28s}  sim={m['similarity']:.3f}  combined={m['combined_distance']:.3f}  type={m.get('doc_type') or '-'}")
        return 0

    matches = match_against_library(target, library, top_k=args.top_k)
    if args.json:
        print(json.dumps(matches, indent=2, ensure_ascii=False))
    else:
        print(f"\ntop {len(matches)} matches for {target.doc_id}:")
        print(f"  {'doc':<28} {'sim':>6} {'script':>8} {'shape':>8} {'combined':>10} {'type':<20}")
        for m in matches:
            print(f"  {m['b']:<28.28s} {m['similarity']:>6.3f} {m['script_distance']:>8.3f} "
                  f"{m['shape_distance']:>8.3f} {m['combined_distance']:>10.3f} {(m.get('doc_type') or '-'):<20}")
    return 0


def cmd_gt_template(args: argparse.Namespace) -> int:
    from transcriber_shell.xml_tools.gt_text import write_template

    src = Path(args.xml).expanduser().resolve()
    if not src.exists():
        print(f"error: not found: {src}", file=sys.stderr)
        return 1

    xmls: list[Path] = []
    if src.is_dir():
        xmls = sorted(src.glob("*.xml"))
    else:
        xmls = [src]
    if not xmls:
        print("error: no XML files found", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else None
    pages_dir = Path(args.pages_dir).expanduser().resolve() if args.pages_dir else None

    for xml in xmls:
        stem = xml.stem
        txt_out = (out_dir / f"{stem}.gt.txt") if out_dir else xml.with_suffix(".gt.txt")
        tiles_dir = None
        image_path = None
        if pages_dir is not None and args.crop_tiles:
            tiles_dir = (out_dir or xml.parent) / f"{stem}.gt_tiles"
            # find matching image
            for ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
                cand = pages_dir / f"{stem}{ext}"
                if cand.is_file():
                    image_path = cand
                    break
            if image_path is None:
                print(f"  skip tiles for {stem}: no matching image in {pages_dir}", file=sys.stderr)
                tiles_dir = None
        try:
            n = write_template(xml, txt_out, image_path=image_path, crop_tiles_dir=tiles_dir)
        except Exception as e:
            print(f"  {xml.name}: failed: {e}", file=sys.stderr)
            continue
        msg = f"  {xml.name}: {n} TextLines → {txt_out.name}"
        if tiles_dir is not None:
            msg += f" + tiles → {tiles_dir.name}/"
        print(msg)
    return 0


def cmd_gt_inject(args: argparse.Namespace) -> int:
    from transcriber_shell.xml_tools.gt_text import inject_text

    src = Path(args.xml).expanduser().resolve()
    if not src.exists():
        print(f"error: not found: {src}", file=sys.stderr)
        return 1

    xmls: list[Path] = []
    if src.is_dir():
        xmls = sorted(src.glob("*.xml"))
    else:
        xmls = [src]
    if not xmls:
        print("error: no XML files found", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else None

    n_total = 0
    n_filled_total = 0
    for xml in xmls:
        txt = xml.with_suffix(".gt.txt")
        if args.txt_dir:
            txt = Path(args.txt_dir).expanduser().resolve() / f"{xml.stem}.gt.txt"
        if not txt.is_file():
            print(f"  skip {xml.name}: no template {txt.name}", file=sys.stderr)
            continue
        out_path = (out_dir / xml.name) if out_dir else None
        try:
            n_lines, n_filled = inject_text(xml, txt, out_path=out_path)
        except Exception as e:
            print(f"  {xml.name}: failed: {e}", file=sys.stderr)
            continue
        n_total += n_lines
        n_filled_total += n_filled
        print(f"  {xml.name}: filled {n_filled}/{n_lines} lines")
    print(f"total: {n_filled_total}/{n_total} TextLines now have ground-truth text")
    return 0


def cmd_gt_filter(args: argparse.Namespace) -> int:
    from transcriber_shell.xml_tools.gt_filter import filter_directory
    src = Path(args.src_dir).expanduser().resolve()
    dst = Path(args.dst_dir).expanduser().resolve()
    if not src.is_dir():
        print(f"error: {src} is not a directory", file=sys.stderr)
        return 1
    stats = filter_directory(src, dst, copy_images=not args.no_copy_images)
    drop_pct = stats["drop_ratio"] * 100
    print(f"filtered {stats['n_files_in']} XMLs → {stats['n_files_kept']} kept")
    print(f"  TextLines: {stats['lines_before']} → {stats['lines_after']} ({drop_pct:.1f}% dropped)")
    if args.verbose:
        for row in stats["rows"]:
            err = f" ERR={row['error']}" if "error" in row else ""
            print(f"  {row['stem']:<32} {row['before']:>4} → {row['after']:>4}{err}")
    return 0


def cmd_gt_split(args: argparse.Namespace) -> int:
    from transcriber_shell.xml_tools.gt_split import write_split_files
    src = Path(args.src_dir).expanduser().resolve()
    train_txt = Path(args.train_out).expanduser().resolve() if args.train_out else src / "train_files.txt"
    val_txt = Path(args.val_out).expanduser().resolve() if args.val_out else src / "val_files.txt"
    if not src.is_dir():
        print(f"error: {src} is not a directory", file=sys.stderr)
        return 1
    stats = write_split_files(
        src, train_txt, val_txt,
        val_fraction=args.val_fraction, seed=args.seed,
    )
    print(f"split: {stats['n_train']} train / {stats['n_val']} val")
    print(f"  train: {train_txt}")
    print(f"  val:   {val_txt}")
    print(f"\n  {'source':<16} {'total':>6} {'train':>6} {'val':>4}")
    for src_key, d in sorted(stats["by_source"].items(), key=lambda kv: -kv[1]["total"]):
        print(f"  {src_key:<16} {d['total']:>6} {d['train']:>6} {d['val']:>4}")
    return 0


def cmd_htr_compare(args: argparse.Namespace) -> int:
    from transcriber_shell.htr.compare import compare_models, format_compare_report
    base = Path(args.base).expanduser().resolve()
    cand = Path(args.candidate).expanduser().resolve()
    gt = Path(args.gt).expanduser().resolve()
    seg = Path(args.seg_model).expanduser().resolve() if args.seg_model else None
    for p, name in [(base, "base"), (cand, "candidate"), (gt, "gt")]:
        if not p.exists():
            print(f"error: {name} not found: {p}", file=sys.stderr)
            return 1
    result = compare_models(base, cand, gt, seg_model=seg, device=args.device,
                            centroid_match_px=args.centroid_match_px)
    print(format_compare_report(result, as_json=args.json), end="")
    return 0


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
    run_skip = run.add_mutually_exclusive_group()
    run_skip.add_argument(
        "--skip-successful",
        dest="skip_successful",
        action="store_const",
        const=True,
        default=True,
        help="Skip run when artifacts/<job_id>/<image_stem>_transcription.yaml already validates (default).",
    )
    run_skip.add_argument(
        "--no-skip-successful",
        dest="skip_successful",
        action="store_const",
        const=False,
        help="Force the pipeline to re-run even when a valid transcription YAML already exists.",
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
        "--htr-model",
        dest="htr_model",
        default=None,
        metavar="NAME",
        help=(
            "Registry name of the HTR model to use (e.g. gm-htr-r2_best). "
            "Overrides --doc-type's HTR pick and TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH. "
            "Use `transcriber-shell list-htr-models` to see candidates."
        ),
    )
    run.add_argument(
        "--auto-doc-type",
        metavar="LIB.json",
        default=None,
        help=(
            "Tagged fingerprint library JSON. Auto-selects --doc-type via fingerprint match. "
            "Ignored if --doc-type is set explicitly."
        ),
    )
    run.add_argument(
        "--auto-min-similarity",
        type=float,
        default=0.5,
        help="Min similarity threshold for --auto-doc-type voting (default 0.5)",
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
            "tesseract_htr",
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
    run.add_argument(
        "--translate",
        dest="translate",
        action="store_true",
        help="After transcription succeeds, run an English translation pass and save <stem>_translation.txt.",
    )
    run.add_argument(
        "--extract-figures",
        dest="extract_figures",
        action="store_true",
        help="After transcription succeeds, run DocLayNet figure detection, save crops, and weave [fig:id] markers into the YAML.",
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
    batch_skip = batch.add_mutually_exclusive_group()
    batch_skip.add_argument(
        "--skip-successful",
        dest="skip_successful",
        action="store_const",
        const=True,
        default=True,
        help="Skip images with an existing valid artifacts/<job_id>/<image_stem>_transcription.yaml (default).",
    )
    batch_skip.add_argument(
        "--no-skip-successful",
        dest="skip_successful",
        action="store_const",
        const=False,
        help="Force the batch to re-run every image, even those with a valid transcription YAML.",
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
        "--htr-model",
        dest="htr_model",
        default=None,
        metavar="NAME",
        help=(
            "Registry name of the HTR model to use across the whole batch. "
            "Overrides --doc-type's HTR pick. See `list-htr-models`."
        ),
    )
    batch.add_argument(
        "--auto-doc-type",
        metavar="LIB.json",
        default=None,
        help=(
            "Tagged fingerprint library JSON. Auto-selects --doc-type per image via "
            "fingerprint match and processes each suggested-type group separately."
        ),
    )
    batch.add_argument(
        "--auto-min-similarity",
        type=float,
        default=0.5,
        help="Min similarity threshold for --auto-doc-type voting (default 0.5)",
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
            "tesseract_htr",
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
    batch.add_argument(
        "--translate",
        dest="translate",
        action="store_true",
        help="After each transcription succeeds, run an English translation pass and save <stem>_translation.txt.",
    )
    batch.add_argument(
        "--extract-figures",
        dest="extract_figures",
        action="store_true",
        help="After each transcription succeeds, run DocLayNet figure detection, save crops, and weave [fig:id] markers into the YAML.",
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
    ci.add_argument("--use-cucim", action="store_true",
                    help="Use cuCIM (GPU) for image resizing; falls back to Pillow if unavailable")
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

    # ── fingerprint ──────────────────────────────────────────────────────────
    fp = sub.add_parser(
        "fingerprint",
        help="Build paleographic fingerprint from ink-component heights in PAGE XML lines",
    )
    fp.add_argument("job_dir", help="Job dir containing 01_pages/ and 02_lines/")
    fp.add_argument("--out", metavar="PATH", default=None,
                    help="Output JSON path (default: <job_dir>/fingerprints.json)")
    fp.add_argument("--doc-type", default=None,
                    help="Tag every fingerprint with this doc-type (for use as a library)")
    fp.add_argument("--min-height-px", type=int, default=4,
                    help="Drop components shorter than this in pixels (default 4)")
    fp.add_argument("--max-height-px", type=int, default=400,
                    help="Drop components taller than this in pixels (default 400)")
    fp.set_defaults(func=cmd_fingerprint)

    # ── fingerprint-compare ──────────────────────────────────────────────────
    fc = sub.add_parser(
        "fingerprint-compare",
        help="Compare fingerprint JSONs (single docs or batches)",
    )
    fc.add_argument("a", help="First fingerprint JSON (single or batch)")
    fc.add_argument("b", nargs="?", default=None,
                    help="Second JSON. Omit to emit pairwise matrix for a single batch JSON.")
    fc.add_argument("--json", action="store_true",
                    help="Print full JSON instead of pretty table")
    fc.set_defaults(func=cmd_fingerprint_compare)

    # ── fingerprint-match ────────────────────────────────────────────────────
    fm = sub.add_parser(
        "fingerprint-match",
        help="Fingerprint one doc and rank against a library; optional doc-type suggestion",
    )
    fm.add_argument("image", help="Target image (e.g. 01_pages/page.jpg)")
    fm.add_argument("library", help="Library fingerprint JSON (batch)")
    fm.add_argument("--lines-xml", default=None,
                    help="Path to PAGE XML for image (default: ../02_lines/<stem>.xml)")
    fm.add_argument("--top-k", type=int, default=5)
    fm.add_argument("--suggest-doc-type", action="store_true",
                    help="Suggest a doc-type by majority vote over top-K typed matches")
    fm.add_argument("--min-similarity", type=float, default=0.5,
                    help="Min similarity for doc-type vote (0–1, default 0.5)")
    fm.add_argument("--json", action="store_true")
    fm.set_defaults(func=cmd_fingerprint_match)

    # ── gt-template ──────────────────────────────────────────────────────────
    gt = sub.add_parser(
        "gt-template",
        help="Emit a numbered .gt.txt template (and optional line-crop tiles) "
             "for manual text-level GT annotation",
    )
    gt.add_argument("xml", help="Single PAGE XML or a directory of XMLs")
    gt.add_argument("--out-dir", metavar="PATH", default=None,
                    help="Write templates here (default: alongside each XML)")
    gt.add_argument("--pages-dir", metavar="PATH", default=None,
                    help="Image dir for --crop-tiles (matches by stem)")
    gt.add_argument("--crop-tiles", action="store_true",
                    help="Also save one PNG per TextLine alongside the template")
    gt.set_defaults(func=cmd_gt_template)

    # ── gt-inject ────────────────────────────────────────────────────────────
    gi = sub.add_parser(
        "gt-inject",
        help="Inject text from .gt.txt template(s) into TextEquiv/Unicode of PAGE XML",
    )
    gi.add_argument("xml", help="Single PAGE XML or a directory of XMLs")
    gi.add_argument("--txt-dir", metavar="PATH", default=None,
                    help="Find <stem>.gt.txt in this dir (default: alongside each XML)")
    gi.add_argument("--out-dir", metavar="PATH", default=None,
                    help="Write updated XMLs here (default: overwrite in place)")
    gi.set_defaults(func=cmd_gt_inject)

    # ── gt-filter ────────────────────────────────────────────────────────────
    gf = sub.add_parser(
        "gt-filter",
        help="Drop TextLines without transcribed text from a PAGE XML GT corpus",
    )
    gf.add_argument("src_dir", help="Source GT directory of *.xml + matching images")
    gf.add_argument("dst_dir", help="Filtered output directory")
    gf.add_argument("--no-copy-images", action="store_true",
                    help="Skip copying matching image files into dst_dir")
    gf.add_argument("--verbose", action="store_true")
    gf.set_defaults(func=cmd_gt_filter)

    # ── gt-split ─────────────────────────────────────────────────────────────
    gs = sub.add_parser(
        "gt-split",
        help="Stratified train/val split by source prefix → ketos -t/-e files",
    )
    gs.add_argument("src_dir", help="GT directory of *.xml files")
    gs.add_argument("--train-out", default=None,
                    help="Path to train_files.txt (default: <src_dir>/train_files.txt)")
    gs.add_argument("--val-out", default=None,
                    help="Path to val_files.txt (default: <src_dir>/val_files.txt)")
    gs.add_argument("--val-fraction", type=float, default=0.1)
    gs.add_argument("--seed", type=int, default=0)
    gs.set_defaults(func=cmd_gt_split)

    # ── htr-compare ──────────────────────────────────────────────────────────
    hc = sub.add_parser(
        "htr-compare",
        help="Compare two Kraken HTR models on a shared GT set (per-page Δ CER)",
    )
    hc.add_argument("base", help="Base / reference Kraken HTR model")
    hc.add_argument("candidate", help="Candidate (fine-tuned) Kraken HTR model")
    hc.add_argument("gt", help="GT directory (PAGE/ALTO XMLs with matching images)")
    hc.add_argument("--seg-model", default=None,
                    help="Optional seg model for baseline accuracy comparison")
    hc.add_argument("--device", default="cpu")
    hc.add_argument("--centroid-match-px", type=int, default=8)
    hc.add_argument("--json", action="store_true")
    hc.set_defaults(func=cmd_htr_compare)

    # ── list-doc-types ───────────────────────────────────────────────────────
    ldt = sub.add_parser("list-doc-types", help="List available document type specs")
    ldt.set_defaults(func=cmd_list_doc_types)

    lhm = sub.add_parser(
        "list-htr-models",
        help="List HTR + segmentation models in the registry (scripts/latin_ms/document_types/models/).",
    )
    lhm.set_defaults(func=cmd_list_htr_models)

    spc = sub.add_parser(
        "score-htr-per-corpus",
        help="Run test-htr against each subdir under EVAL_DIR and report per-corpus CER.",
    )
    spc.add_argument("--model", "-m", default=None, metavar="NAME",
                     help="Registry name of the HTR model (e.g. gm-htr-r2_best).")
    spc.add_argument("--model-path", default=None, metavar="PATH",
                     help="Direct .mlmodel path (alternative to --model).")
    spc.add_argument("--eval-dir", "-e", required=True, metavar="DIR",
                     help="Directory of per-corpus subdirectories; each holds XML or PNG+.gt.txt pairs.")
    spc.add_argument("--seg-model", "-s", default=None, metavar="PATH",
                     help="Optional kraken segmentation model for baseline accuracy.")
    spc.add_argument("--device", "-d", default="cpu",
                     help="ketos/kraken device (cpu, mps, cuda:0).")
    spc.add_argument("--centroid-match-px", type=float, default=120.0,
                     help="Centroid distance for baseline matching when seg-model provided.")
    spc.add_argument("--json", action="store_true",
                     help="Print the per-corpus CER dict as JSON after the table.")
    spc.add_argument("--update-registry", action="store_true",
                     help="Write metrics.per_corpus_cer back into the model's registry YAML.")
    spc.set_defaults(func=cmd_score_htr_per_corpus)

    args = ap.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
