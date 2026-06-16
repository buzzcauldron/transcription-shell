#!/usr/bin/env python3
"""Run transcription-shell (Kraken lineation → GM HTR → LLM correct) on protocol stress cases.

The protocol prompt (from manifest + prompt-templates-v1.1.0.md) guides the LLM to fix
HTR drafts — ground-truth *.md files are never sent to the model (scoring only).

Saves response.txt under benchmark/test-results/stress/<case>/shell-<htr>-<llm>/
then runs stress_replay to refresh stress_report.md.

Usage (from transcription-shell repo root):
  python scripts/stress_shell_run.py --include-optional
  python scripts/stress_shell_run.py --cases BM-KB27 BM-MED-001 --htr r5 r2
  python scripts/stress_shell_run.py --replay-only

After a matrix run, generate an HTR training plan from weaknesses:
  python scripts/blind_test_training_plan.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
PROTO = REPO / "vendor" / "transcription-protocol"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

HTR_MODELS = {
    "r2": Path(os.environ.get("GM_HTR_R2", "~/src/latin_documents/gm-htr-r2.mlmodel_best.mlmodel")).expanduser(),
    "r5": Path(os.environ.get("GM_HTR_R5", "~/src/latin_documents/gm-htr-r5-best.mlmodel")).expanduser(),
    "computus": Path(os.environ.get("GM_HTR_COMPUTUS", "~/src/latin_documents/gm-htr-computus_best.mlmodel")).expanduser(),
    "anglicana": Path(
        os.environ.get("GM_HTR_ANGLICANA", "~/src/latin_documents/gm-htr-anglicana_best.mlmodel")
    ).expanduser(),
    "psalter": Path(
        os.environ.get("GM_HTR_PSALTER", "~/src/latin_documents/gm-htr-psalter_best.mlmodel")
    ).expanduser(),
}
SEG_MODEL = Path(os.environ.get("KRAKEN_SEG", "~/src/latin_documents/kraken-merged-seg.mlmodel_best.mlmodel")).expanduser()

# Glyph Machina local HTR repo (best_HTR.net lives here; requires CUDA GPU — run on akdeniz or Bridges).
GM_HTR_REPO = Path(os.environ.get("TRANSCRIBER_SHELL_GM_HTR_REPO_PATH", "~/src/glyph_machina_public")).expanduser()

# Best HTR pick per manifest evaluator (override with --htr on CLI).
HTR_BY_EVALUATOR: dict[str, str] = {
    # Latin — GM local HTR (best_HTR.net); falls back to GM web if no local repo.
    "medieval": "gm",
    "legal": "gm",
    # Modern English copperplate — computus outperforms r2 across all three LOC cases.
    "lincoln": "computus",
    "modern_lovejoy": "computus",
    "modern_deed": "computus",
    # Early-modern English and BM-MOD-JOHNSON — r5 is best available (r2 equivalent).
    "earlymodern": "r5",
    "modern_johnson": "r5",
}

# Cross-era blind matrix: run every available HTR on every case.
ALL_HTR_KEYS = ("gm", "r2", "r5", "computus", "anglicana", "psalter")


def _merge_yaml_pages(docs: list[dict]) -> str:
    """Merge per-page transcription YAML into one document."""
    if not docs:
        return ""
    if len(docs) == 1:
        return yaml.dump(docs[0], allow_unicode=True, sort_keys=False)

    base = docs[0]
    root_key = "transcriptionOutput" if "transcriptionOutput" in base else None
    if root_key:
        out = base[root_key]
        segs = list(out.get("segments") or [])
        next_id = max((int(s.get("segmentId", 0)) for s in segs if isinstance(s, dict)), default=0) + 1
        for doc in docs[1:]:
            other = doc.get("transcriptionOutput", doc)
            for s in other.get("segments") or []:
                if isinstance(s, dict):
                    s = dict(s)
                    s["segmentId"] = next_id
                    next_id += 1
                    segs.append(s)
        out["segments"] = segs
        return yaml.dump({root_key: out}, allow_unicode=True, sort_keys=False)

    segs = []
    for doc in docs:
        segs.extend(doc.get("segments") or [])
    return yaml.dump({"segments": segs}, allow_unicode=True, sort_keys=False)


def run_shell_case(
    *,
    case_id: str,
    image_paths: list[Path],
    prompt_cfg: dict,
    htr_key: str,
    llm_provider: str,
    llm_model: str,
    llm_mode: str,
    artifacts: Path,
) -> tuple[str, list[str]]:
    from transcriber_shell.config import Settings
    from transcriber_shell.models.job import TranscribeJob
    from transcriber_shell.pipeline.run import run_pipeline

    if not SEG_MODEL.is_file():
        raise FileNotFoundError(f"Seg model missing: {SEG_MODEL}")

    if htr_key == "gm":
        if GM_HTR_REPO.is_dir():
            # Local GM HTR — works on CUDA (akdeniz/Bridges), MPS (Apple Silicon), or CPU.
            # run_gm_htr patches the device line at runtime; no upstream modification needed.
            settings = Settings(
                artifacts_dir=artifacts,
                lineation_backend="kraken",
                kraken_model_path=SEG_MODEL,
                gm_htr_repo_path=GM_HTR_REPO,
                htr_combination="sequential",
                llm_mode=llm_mode,
                protocol_repo_path=PROTO,
            )
        else:
            # Web fallback — Playwright against the GM website (no GPU required).
            print(
                f"[gm] local repo not found at {GM_HTR_REPO}, "
                "falling back to Glyph Machina web service"
            )
            settings = Settings(
                artifacts_dir=artifacts,
                lineation_backend="glyph_machina",
                htr_combination="shell",
                llm_mode=llm_mode,
                protocol_repo_path=PROTO,
            )
    else:
        htr_path = HTR_MODELS[htr_key]
        if not htr_path.is_file():
            raise FileNotFoundError(f"HTR model missing: {htr_path}")
        settings = Settings(
            artifacts_dir=artifacts,
            lineation_backend="kraken",
            kraken_model_path=SEG_MODEL,
            kraken_htr_model_path=htr_path,
            htr_combination="sequential",
            llm_mode=llm_mode,
            protocol_repo_path=PROTO,
        )

    docs: list[dict] = []
    errors: list[str] = []
    for i, img in enumerate(image_paths):
        job = TranscribeJob(
            job_id=f"{case_id}-p{i + 1}",
            image_path=img,
            prompt_cfg=dict(prompt_cfg),
            provider=llm_provider,
            model_override=llm_model,
        )
        result = run_pipeline(job, settings=settings)
        if result.errors:
            errors.extend(result.errors)
        if result.transcription_yaml_path and result.transcription_yaml_path.is_file():
            docs.append(yaml.safe_load(result.transcription_yaml_path.read_text(encoding="utf-8")))

    if errors and not docs:
        return f"ERROR: {'; '.join(errors)}", errors
    return _merge_yaml_pages(docs), errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Shell pipeline stress runs + replay score")
    ap.add_argument("--manifest", type=Path, default=PROTO / "benchmark" / "manifest.yaml")
    ap.add_argument("--output-dir", type=Path, default=REPO / "benchmark" / "results" / "stress")
    ap.add_argument("--cases", nargs="*", default=None)
    ap.add_argument("--include-optional", action="store_true")
    ap.add_argument("--htr", nargs="*", choices=["gm"] + list(HTR_MODELS), default=None, help="HTR models to run (default: per evaluator)")
    ap.add_argument(
        "--all-htr",
        action="store_true",
        help="Run all available HTR models on every case (skips missing weights)",
    )
    ap.add_argument("--llm-provider", default=os.environ.get("STRESS_SHELL_LLM_PROVIDER", "gemini"))
    ap.add_argument("--llm-model", default=os.environ.get("STRESS_SHELL_LLM_MODEL", "gemini-2.5-pro"))
    ap.add_argument(
        "--llm-mode",
        choices=("correct", "full"),
        default=os.environ.get("STRESS_SHELL_LLM_MODE", "correct"),
        help="full = image-primary transcription; correct = fix HTR draft (default)",
    )
    ap.add_argument("--replay-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.replay_only:
        return subprocess.call(
            [sys.executable, "-m", "benchmark.stress_replay", "--include-optional"],
            cwd=str(PROTO),
        )

    from benchmark.stress_run import ensure_images
    from benchmark.stress_common import load_manifest, load_env_file

    load_env_file(PROTO)
    manifest = load_manifest(args.manifest)
    cases_cfg = manifest.get("cases") or {}

    case_ids = list(cases_cfg.keys())
    if args.cases:
        case_ids = [c for c in args.cases if c in cases_cfg]

    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    artifacts = REPO / "artifacts" / "stress-shell"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for case_id in case_ids:
        cfg = cases_cfg[case_id]
        if cfg.get("optional") and not args.include_optional:
            print(f"[skip] optional {case_id}")
            continue
        try:
            imgs = [Path(p) for p in ensure_images(case_id, cfg, PROTO)]
        except FileNotFoundError as e:
            print(f"[skip] {case_id}: {e}")
            continue
        if not imgs:
            print(f"[skip] {case_id}: no images")
            continue

        evaluator = cfg.get("evaluator", "lincoln")
        def _htr_available(k: str) -> bool:
            if k == "gm":
                return True  # local preferred; falls back to GM web service
            return HTR_MODELS[k].is_file()

        if args.all_htr:
            htr_keys = [k for k in ALL_HTR_KEYS if _htr_available(k)]
        elif args.htr:
            htr_keys = args.htr
        else:
            preferred = HTR_BY_EVALUATOR.get(evaluator, "r2")
            if _htr_available(preferred):
                htr_keys = [preferred]
            else:
                htr_keys = [k for k in ALL_HTR_KEYS if _htr_available(k)][:1]
        prompt_cfg = dict(cfg.get("prompt") or {})

        for hk in htr_keys:
            if not _htr_available(hk):
                print(f"[skip] {case_id} htr={hk}: missing {HTR_MODELS[hk]}")
                continue
            mode_tag = args.llm_mode if args.llm_mode != "correct" else ""
            # Include a short model slug so different LLM models don't overwrite each other.
            model_slug = args.llm_model.split("/")[-1].replace(".", "-").replace("_", "-") if args.llm_model else args.llm_provider
            label_parts = ["shell"] + ([mode_tag] if mode_tag else []) + [hk, model_slug]
            run_label = "-".join(label_parts)
            out_dir = args.output_dir / case_id / run_label
            out_dir.mkdir(parents=True, exist_ok=True)
            resp_path = out_dir / "response.txt"
            meta_path = out_dir / "meta.json"

            if args.dry_run:
                print(f"[dry-run] {case_id} htr={hk} -> {out_dir}")
                continue

            print(
                f"[run] {case_id} htr={hk} llm_mode={args.llm_mode} "
                f"llm={args.llm_provider}/{args.llm_model} images={len(imgs)}"
            )
            try:
                raw, errs = run_shell_case(
                    case_id=case_id,
                    image_paths=imgs,
                    prompt_cfg=prompt_cfg,
                    htr_key=hk,
                    llm_provider=args.llm_provider,
                    llm_model=args.llm_model,
                    llm_mode=args.llm_mode,
                    artifacts=artifacts / case_id / f"{args.llm_mode}-{hk}",
                )
            except Exception as e:
                raw = f"ERROR: {e}"
                errs = [str(e)]

            resp_path.write_text(raw, encoding="utf-8")
            meta_path.write_text(
                json.dumps(
                    {
                        "caseId": case_id,
                        "modelKey": run_label,
                        "modelId": args.llm_model,
                        "htrModel": str(GM_HTR_REPO / "best_HTR.net") if hk == "gm" else str(HTR_MODELS[hk]),
                        "llmProvider": args.llm_provider,
                        "pipeline": (
                            f"transcription-shell: kraken seg → glyph-machina HTR → llm_mode={args.llm_mode}"
                            if hk == "gm"
                            else f"transcription-shell: kraken seg → kraken HTR ({hk}) → llm_mode={args.llm_mode}"
                        ),
                        "llmMode": args.llm_mode,
                        "started": started,
                        "warnings": errs,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"  -> {resp_path}")

    if args.dry_run:
        return 0

    print("[replay] scoring all response.txt under stress/")
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "benchmark.stress_replay",
            "--include-optional",
            "--output-dir",
            str(args.output_dir),
        ],
        cwd=str(PROTO),
    )


if __name__ == "__main__":
    raise SystemExit(main())
