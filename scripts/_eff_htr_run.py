#!/usr/bin/env python3
"""Bridges GPU-node HTR efficiency runner (invoked from efficiency_htr.sbatch / sbatch --wrap)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import yaml

from transcriber_shell.config import Settings
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.run import run_pipeline
from transcriber_shell.runtime.machine_profile import (
    apply_machine_efficiency,
    detect_machine_profile,
    recommend_settings,
)


def main() -> int:
    out = Path(os.environ["OUT_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    fix = Path(os.environ["FIX_DIR"])

    prof = detect_machine_profile()
    rec = recommend_settings(prof)
    (out / "profile.json").write_text(
        json.dumps({"profile": prof.to_dict(), "recommend": rec}, indent=2),
        encoding="utf-8",
    )
    print("profile", prof.alias, prof.host_class, prof.gpu_name, flush=True)
    print("recommend", rec["updates"], flush=True)

    imgs = sorted(fix.glob("*.jpg")) + sorted(fix.glob("*.png"))
    xmls = {p.stem: p for p in fix.glob("*.xml")}
    if not imgs:
        raise SystemExit(f"no page image in {fix}")
    image = imgs[0]
    lines = xmls.get(image.stem)
    prompt_path = fix / "prompt.example.yaml"
    prompt_cfg = (
        yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
        if prompt_path.is_file()
        else {
            "targetLanguage": "lat-Latn",
            "normalizationMode": "diplomatic",
            "runMode": "efficient",
            "protocolVersion": "1.1.0",
        }
    )

    s = Settings(
        artifacts_dir=out / "artifacts",
        llm_mode="off",
        htr_combination="kraken_htr_only",
        lineation_backend="kraken",
        reuse_lines_xml=True,
    )
    s, _, msgs = apply_machine_efficiency(s, profile=prof)
    s = s.model_copy(update={"llm_mode": "off", "htr_combination": "kraken_htr_only"})
    for m in msgs:
        print("auto-efficiency:", m, flush=True)

    htr = os.environ.get("TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH")
    if htr:
        s = s.model_copy(update={"kraken_htr_model_path": Path(htr)})
    seg = os.environ.get("TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH")
    if seg:
        s = s.model_copy(update={"kraken_model_path": Path(seg)})

    job = TranscribeJob(
        job_id="eff-bridges-gpu",
        image_path=image,
        prompt_cfg=prompt_cfg,
        provider="gemini",
    )
    skip_gm = lines is not None and lines.is_file()
    t0 = time.perf_counter()
    res = run_pipeline(
        job,
        skip_gm=skip_gm,
        lines_xml_path=lines if skip_gm else None,
        settings=s,
        log_fn=lambda m: print(m, flush=True),
    )
    wall = time.perf_counter() - t0
    summary = {
        "host": "bridges_gpu",
        "wall_s": round(wall, 3),
        "timings": {k: round(v, 3) for k, v in (res.timings or [])},
        "ok": not res.errors,
        "errors": list(res.errors or [])[:8],
        "warnings": list(res.warnings or [])[:8],
        "image": str(image),
        "skip_gm": skip_gm,
        "settings": {
            "batch_parallel_pages": s.batch_parallel_pages,
            "llm_mode": s.llm_mode,
            "htr_combination": s.htr_combination,
            "lineation_backend": s.lineation_backend,
        },
        "gpu_name": prof.gpu_name,
        "slurm_job_id": prof.slurm_job_id,
        "slurm_partition": prof.slurm_partition,
    }
    (out / "htr_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if not res.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
