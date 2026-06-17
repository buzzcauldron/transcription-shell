#!/usr/bin/env python3
"""Run cross-provider protocol harness on stress manifest cases.

Uses benchmark/transcription_harness.py (Protocol 1.2.0 structured JSON) to compare
Claude, OpenAI, and Gemini on uncertainty flooding and verifier addition-rate.
Ground-truth files are never sent to models.

Usage (from transcription-shell repo root):
  python scripts/protocol_harness_run.py --mock
  python scripts/protocol_harness_run.py --cases BM-KB27 --providers claude openai
  python scripts/protocol_harness_run.py --include-optional --verifier openai

Requires API keys in the environment (see vendor/transcription-protocol/.env.example).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROTO = REPO / "vendor" / "transcription-protocol"
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from benchmark.stress_common import load_env_file, load_manifest, repo_root  # noqa: E402
from benchmark.stress_run import ensure_images  # noqa: E402
from benchmark.transcription_harness import (  # noqa: E402
    prepare_api_keys,
    render_report,
    run_comparison,
    run_mock,
)


def _prompt_to_config(prompt: dict) -> dict:
    cfg = {
        "sourcePageId": prompt.get("sourcePageId"),
        "protocolVersion": prompt.get("protocolVersion", "1.2.0"),
        "targetLanguage": prompt.get("targetLanguage"),
        "targetEra": prompt.get("targetEra"),
        "diplomaticProfile": prompt.get("diplomaticProfile"),
        "normalizationMode": prompt.get("normalizationMode"),
        "runMode": "standard",
        "englishHandwritingModality": prompt.get("englishHandwritingModality"),
    }
    return {k: v for k, v in cfg.items() if v is not None}


def main(argv: list[str] | None = None) -> int:
    root = repo_root()
    load_env_file(root)
    prepare_api_keys()

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=root / "benchmark" / "manifest.yaml")
    ap.add_argument("--cases", nargs="*", help="Case IDs (default: all non-optional)")
    ap.add_argument("--include-optional", action="store_true")
    ap.add_argument(
        "--providers",
        nargs="+",
        default=["claude", "openai"],
        help="Transcription providers (claude, openai, gemini, anthropic)",
    )
    ap.add_argument("--verifier", help="Cross-provider verifier (default: first provider != subject)")
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=root / "benchmark" / "test-results" / "harness",
    )
    ap.add_argument("--mock", action="store_true", help="Exercise metrics with no API calls")
    ap.add_argument("--dry-run", action="store_true", help="Resolve images only")
    args = ap.parse_args(argv)

    if args.mock:
        run_mock()
        return 0

    manifest = load_manifest(args.manifest)
    cases_cfg = manifest.get("cases") or {}
    case_ids = list(cases_cfg.keys())
    if args.cases:
        case_ids = [c for c in args.cases if c in cases_cfg]
        unknown = set(args.cases) - set(cases_cfg.keys())
        if unknown:
            print(f"Unknown cases: {unknown}", file=sys.stderr)
            return 1

    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []

    for case_id in case_ids:
        case_cfg = cases_cfg[case_id]
        if case_cfg.get("optional") and not args.include_optional:
            print(f"Skip optional {case_id} (use --include-optional)")
            continue
        try:
            image_paths = ensure_images(case_id, case_cfg, root)
        except FileNotFoundError as e:
            print(f"Skip {case_id}: {e}")
            continue
        if not image_paths:
            print(f"Skip {case_id}: no images")
            continue

        image_path = image_paths[0]
        if len(image_paths) > 1:
            print(f"{case_id}: harness uses first page only ({len(image_paths)} available)")

        config = _prompt_to_config(case_cfg.get("prompt") or {})
        verifier = args.verifier
        if not verifier and len(args.providers) > 1:
            verifier = args.providers[0]

        if args.dry_run:
            print(f"[dry-run] {case_id}: {image_path} providers={args.providers} verifier={verifier}")
            continue

        print(f"Running harness: {case_id} …")
        result = run_comparison(image_path, config, args.providers, verifier)
        report = render_report(result)
        case_dir = args.output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "harness_report.md").write_text(report, encoding="utf-8")
        (case_dir / "harness_result.json").write_text(
            json.dumps(
                {
                    "caseId": case_id,
                    "image": image_path,
                    "config": config,
                    "providers": args.providers,
                    "verifier": verifier,
                    "started": started,
                    **{k: v for k, v in result.items() if k != "transcripts"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        for prov, transcript in result.get("transcripts", {}).items():
            (case_dir / f"{prov}_transcript.json").write_text(
                json.dumps(transcript, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        summary.append(
            {
                "case": case_id,
                "metrics": result.get("metrics", {}),
                "addition_rates": result.get("addition_rates", {}),
                "errors": result.get("errors", {}),
            }
        )
        print(report)

    if args.dry_run:
        return 0

    summary_path = args.output_dir / "harness_summary.json"
    summary_path.write_text(
        json.dumps({"generated": started, "cases": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
