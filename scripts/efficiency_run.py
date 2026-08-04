#!/usr/bin/env python3
"""Thorough pipeline efficiency run — microbenches + page/batch stage timings.

Writes:
  benchmark/results/efficiency/<timestamp>/summary.json
  benchmark/results/efficiency/<timestamp>/report.md

Usage (repo root):
  python scripts/efficiency_run.py
  python scripts/efficiency_run.py --micro-only
  python scripts/efficiency_run.py --skip-llm --batch-pages 3
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
PROTO = REPO / "vendor" / "transcription-protocol"
sys.path.insert(0, str(SRC))
if PROTO.is_dir():
    sys.path.insert(0, str(PROTO))

NYPL = Path.home() / "latin-ms-workspace/jobs/nypl_computus_text_3"
HTR_COMPUTUS = Path.home() / "src/latin_documents/gm-htr-computus_best.mlmodel"
SEG_MODEL = Path.home() / "src/latin_documents/kraken-merged-seg.mlmodel_best.mlmodel"
STYLO_REF = Path.home() / "Projects/stylometry-r/output/de_luce_r_rescore/reference_set_medieval_mixed"
BM_LAT = (
    REPO
    / "vendor/transcription-protocol/benchmark/images/BM-LAT-001/SBB_PK_Mgo511_025r.png"
)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _timed(fn: Callable[[], Any], *, repeats: int = 1) -> dict[str, Any]:
    times: list[float] = []
    result = None
    err = None
    for _ in range(max(1, repeats)):
        t0 = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            times.append(time.perf_counter() - t0)
            break
        times.append(time.perf_counter() - t0)
    out: dict[str, Any] = {
        "seconds": times[-1] if times else None,
        "repeats": len(times),
        "mean_s": statistics.mean(times) if times else None,
        "min_s": min(times) if times else None,
        "max_s": max(times) if times else None,
    }
    if err:
        out["error"] = err
    if result is not None and not callable(result):
        try:
            json.dumps(result)
            out["result"] = result
        except TypeError:
            out["result_repr"] = repr(result)[:200]
    return out


def discover_page_pairs(n: int = 5) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    lines = NYPL / "02_lines"
    pages = NYPL / "01_pages"
    if not lines.is_dir() or not pages.is_dir():
        return pairs
    for xml in sorted(lines.glob("*.xml")):
        img = pages / f"{xml.stem}.jpg"
        if not img.is_file():
            img = pages / f"{xml.stem}.png"
        if img.is_file():
            pairs.append((img, xml))
        if len(pairs) >= n:
            break
    return pairs


def _stylo_once(text: str) -> dict[str, Any]:
    from transcriber_shell.stylometry.stylo_run import analyze_text

    s = analyze_text(text, ref_dir=STYLO_REF)
    return {
        "primary": s.primary_register,
        "secondary": s.secondary_content,
        "n_words": s.n_words,
        "fw_windows": s.n_function_windows,
        "mfw_windows": s.n_mfw_windows,
    }


def bench_micro() -> dict[str, Any]:
    from transcriber_shell.document_types import load_doc_type
    from transcriber_shell.htr import model_registry
    from transcriber_shell.llm.correct_prompt import build_correct_prompts
    from transcriber_shell.stylometry.genre_signal import compute_genre_signal

    out: dict[str, Any] = {}

    out["registry_load_all"] = _timed(lambda: {"n": len(model_registry.load_all())}, repeats=5)
    names = [s.name for s in model_registry.load_all()]
    out["registry_by_name_x10"] = _timed(
        lambda: [model_registry.by_name(n) for n in (names * 3)[:10]],
        repeats=5,
    )

    doc_dir = REPO / "scripts/latin_ms/document_types"
    yamls = sorted(doc_dir.glob("*.yaml")) if doc_dir.is_dir() else []

    def _load_docs() -> dict[str, Any]:
        ok = 0
        errs: list[str] = []
        for y in yamls:
            try:
                load_doc_type(y.stem)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                errs.append(f"{y.name}:{exc}")
        return {"n": ok, "errors": errs[:3]}

    out["doc_types_load_all"] = _timed(_load_docs, repeats=3)

    import yaml

    prompt_path = REPO / "fixtures/prompt.example.yaml"
    prompt_cfg = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))

    try:
        from prompt_builder import build_zones  # type: ignore

        out["prompt_build_full"] = _timed(
            lambda: {"chars": sum(len(x) for x in build_zones(prompt_cfg))},
            repeats=10,
        )
    except Exception as exc:  # noqa: BLE001
        out["prompt_build_full"] = {"error": str(exc)}

    fake_hint = "\n".join(
        f"L{i}: et in principio erat verbum et verbum erat" for i in range(1, 41)
    )
    out["prompt_build_correct"] = _timed(
        lambda: {
            "chars": sum(
                len(x)
                for x in build_correct_prompts(
                    line_hint=fake_hint,
                    normalization_mode="diplomatic",
                    language_hint="lat-Latn",
                )
            )
        },
        repeats=20,
    )

    yaml_sample = Path.home() / (
        "latin-ms-workspace/jobs/pal_lat_1407/03_artifacts_2500/"
        "Pal.lat.1407.f.063r/Pal.lat.1407.f.063r_transcription.yaml"
    )
    if yaml_sample.is_file():
        from transcriber_shell.llm.validate_output import validate_transcript_file

        sys.path.insert(0, str(REPO / "scripts"))
        from extract_corpus_text import extract_yaml_text  # type: ignore

        out["yaml_validate"] = _timed(
            lambda: {"ok": bool(validate_transcript_file(yaml_sample))},
            repeats=5,
        )
        out["yaml_extract"] = _timed(
            lambda: {"chars": len(extract_yaml_text(yaml_sample, layer="normalized"))},
            repeats=10,
        )

    sample_latin = (
        "Anno igitur ab incarnatione domini nostri ihesu christi "
        "dccccxcviiii indictione vii epacta xxvi concurrentes v "
        "lunae xiiii paschalis xii kalendas aprilis. "
        "Computus est scientia temporum distinguendorum. "
    ) * 40
    out["genre_signal_internal"] = _timed(
        lambda: {
            "repr": str(
                compute_genre_signal(
                    [sample_latin],
                    "efficiency_sample",
                    prefer_external=False,
                )
            )[:120]
        },
        repeats=3,
    )

    if STYLO_REF.is_dir():
        text_path = NYPL / "nypl_computus_text_3_body_text.txt"
        text = (
            text_path.read_text(encoding="utf-8", errors="replace")[:12000]
            if text_path.is_file()
            else sample_latin * 5
        )
        out["stylo_analyze_text"] = _timed(lambda: _stylo_once(text), repeats=1)
    else:
        out["stylo_analyze_text"] = {"error": f"missing ref {STYLO_REF}"}

    pairs = discover_page_pairs(1)
    if pairs:
        from transcriber_shell.xml_tools.lines_validate import validate_lines_xml

        out["xml_validate_lines"] = _timed(
            lambda: {"ok": validate_lines_xml(str(pairs[0][1]))[0]},
            repeats=5,
        )

    return out


def _base_settings(**updates: Any):
    from transcriber_shell.config import Settings

    env = {
        "TRANSCRIBER_SHELL_HTR_COMBINATION": "kraken_htr",
        "TRANSCRIBER_SHELL_LINEATION_BACKEND": "kraken",
        "TRANSCRIBER_SHELL_BATCH_PARALLEL_PAGES": "1",
        "TRANSCRIBER_SHELL_REUSE_LINES_XML": "true",
    }
    if HTR_COMPUTUS.is_file():
        env["TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH"] = str(HTR_COMPUTUS)
    if SEG_MODEL.is_file():
        env["TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH"] = str(SEG_MODEL)
    for k, v in env.items():
        os.environ.setdefault(k, v)
    s = Settings()
    if updates:
        s = s.model_copy(update=updates)
    return s


def run_one_page(
    *,
    image: Path,
    lines_xml: Path | None,
    job_id: str,
    artifacts: Path,
    llm_mode: str,
    skip_gm: bool,
    provider: str | None = None,
) -> dict[str, Any]:
    import yaml
    from transcriber_shell.models.job import TranscribeJob
    from transcriber_shell.pipeline.run import run_pipeline

    prompt_cfg = yaml.safe_load(
        (REPO / "fixtures/prompt.example.yaml").read_text(encoding="utf-8")
    )
    updates: dict[str, Any] = {
        "artifacts_dir": artifacts,
        "llm_mode": llm_mode,
        "htr_combination": "kraken_htr_only" if llm_mode == "off" else "kraken_htr",
        "reuse_lines_xml": True,
        "lineation_backend": "kraken",
    }
    if provider:
        updates["default_provider"] = provider
    if HTR_COMPUTUS.is_file():
        updates["kraken_htr_model_path"] = HTR_COMPUTUS
    s = _base_settings(**updates)

    prov = provider or s.default_provider
    job = TranscribeJob(
        job_id=job_id,
        image_path=image,
        prompt_cfg=prompt_cfg,
        provider=prov,
        model_override=s.resolved_model(prov),
    )
    wall0 = time.perf_counter()
    result = run_pipeline(
        job,
        skip_gm=skip_gm,
        lines_xml_path=lines_xml,
        settings=s,
        log_fn=lambda m: print(f"  [{job_id}] {m}", flush=True),
    )
    wall = time.perf_counter() - wall0
    return {
        "job_id": job_id,
        "image": str(image),
        "llm_mode": llm_mode,
        "skip_gm": skip_gm,
        "wall_s": round(wall, 3),
        "timings": {k: round(v, 3) for k, v in (result.timings or [])},
        "ok": not result.errors,
        "errors": list(result.errors or [])[:5],
        "warnings": list(result.warnings or [])[:5],
        "text_line_count": result.text_line_count,
        "llm_usage": getattr(result, "llm_usage", None),
    }


def bench_pages(*, skip_llm: bool, include_lineation: bool) -> dict[str, Any]:
    pairs = discover_page_pairs(1)
    if not pairs:
        return {"error": "no NYPL page/xml pairs"}
    image, xml = pairs[0]
    artifacts = REPO / "benchmark/results/efficiency" / "_work" / "pages"
    artifacts.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {"fixture": {"image": str(image), "lines_xml": str(xml)}}

    out["page_htr_only"] = run_one_page(
        image=image,
        lines_xml=xml,
        job_id=f"eff-htr-{image.stem}",
        artifacts=artifacts,
        llm_mode="off",
        skip_gm=True,
    )
    out["page_htr_only_second"] = run_one_page(
        image=image,
        lines_xml=xml,
        job_id=f"eff-htr2-{image.stem}",
        artifacts=artifacts,
        llm_mode="off",
        skip_gm=True,
    )

    if include_lineation and SEG_MODEL.is_file() and BM_LAT.is_file():
        out["page_lineation_cold"] = run_one_page(
            image=BM_LAT,
            lines_xml=None,
            job_id="eff-lin-cold-bmlat",
            artifacts=artifacts,
            llm_mode="off",
            skip_gm=False,
        )
        out["page_lineation_reuse"] = run_one_page(
            image=BM_LAT,
            lines_xml=None,
            job_id="eff-lin-cold-bmlat",
            artifacts=artifacts,
            llm_mode="off",
            skip_gm=False,
        )

    if skip_llm:
        return out

    key = os.environ.get("GOOGLE_API_KEY") or ""
    if not key.startswith("AIza"):
        out["llm_skip"] = "GOOGLE_API_KEY missing/invalid shape"
        return out

    out["page_llm_correct"] = run_one_page(
        image=image,
        lines_xml=xml,
        job_id=f"eff-correct-{image.stem}",
        artifacts=artifacts,
        llm_mode="correct",
        skip_gm=True,
        provider="gemini",
    )
    out["page_llm_full"] = run_one_page(
        image=image,
        lines_xml=xml,
        job_id=f"eff-full-{image.stem}",
        artifacts=artifacts,
        llm_mode="full",
        skip_gm=True,
        provider="gemini",
    )
    return out


def bench_batch(n_pages: int, parallel: int) -> dict[str, Any]:
    pairs = discover_page_pairs(n_pages)
    if len(pairs) < 2:
        return {"error": "need >=2 page pairs", "n": len(pairs)}
    artifacts = REPO / "benchmark/results/efficiency" / "_work" / f"batch_p{parallel}"
    artifacts.mkdir(parents=True, exist_ok=True)

    def _one(idx_pair: tuple[int, tuple[Path, Path]]) -> dict[str, Any]:
        _, (img, xml) = idx_pair
        return run_one_page(
            image=img,
            lines_xml=xml,
            job_id=f"eff-b{parallel}-{img.stem}",
            artifacts=artifacts,
            llm_mode="off",
            skip_gm=True,
        )

    wall0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futs = [ex.submit(_one, (i, p)) for i, p in enumerate(pairs)]
        for f in as_completed(futs):
            rows.append(f.result())
    wall = time.perf_counter() - wall0
    stage_sums = {"htr": 0.0, "lineation": 0.0, "llm": 0.0}
    for r in rows:
        for k, v in (r.get("timings") or {}).items():
            if k in stage_sums:
                stage_sums[k] += float(v)
    return {
        "parallel": parallel,
        "n_pages": len(pairs),
        "wall_s": round(wall, 3),
        "sum_htr_s": round(stage_sums["htr"], 3),
        "efficiency_vs_serial": round(stage_sums["htr"] / wall, 3) if wall else None,
        "pages": rows,
    }


def write_report(summary: dict[str, Any], out_dir: Path) -> Path:
    lines: list[str] = [
        "# Pipeline efficiency report",
        "",
        f"_Generated {summary.get('stamp')} UTC_",
        "",
        "## Microbenches (CPU)",
        "",
        "| Stage | mean s | notes |",
        "|---|---:|---|",
    ]
    micro = summary.get("micro") or {}
    for key, val in micro.items():
        if not isinstance(val, dict):
            continue
        mean = val.get("mean_s")
        note = val.get("error") or json.dumps(val.get("result") or val.get("result_repr") or "")[:80]
        lines.append(f"| `{key}` | {mean if mean is not None else '—'} | {note} |")
    lines.append("")
    lines.append("## Page pipeline")
    lines.append("")
    pages = summary.get("pages") or {}
    for key in (
        "page_htr_only",
        "page_htr_only_second",
        "page_lineation_cold",
        "page_lineation_reuse",
        "page_llm_correct",
        "page_llm_full",
    ):
        row = pages.get(key)
        if not row:
            continue
        if "error" in row and "wall_s" not in row:
            lines.append(f"- **{key}**: error `{row['error']}`")
            continue
        timings = row.get("timings") or {}
        lines.append(
            f"- **{key}**: wall **{row.get('wall_s')}s** "
            f"timings={timings} ok={row.get('ok')} "
            f"errors={row.get('errors')}"
        )
    lines.append("")
    lines.append("## Batch parallelism (HTR-only)")
    lines.append("")
    batch = summary.get("batch") or {}
    for label, b in batch.items():
        if not isinstance(b, dict) or "wall_s" not in b:
            lines.append(f"- **{label}**: {b}")
            continue
        lines.append(
            f"- **{label}**: wall **{b['wall_s']}s** for {b.get('n_pages')} pages; "
            f"sum(htr)={b.get('sum_htr_s')}s; "
            f"parallel efficiency={b.get('efficiency_vs_serial')}×"
        )
    lines.append("")
    lines.append("## Bottleneck callouts")
    lines.append("")
    for c in summary.get("callouts") or []:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    for r in summary.get("recommendations") or []:
        lines.append(f"- {r}")
    lines.append("")
    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def derive_callouts(summary: dict[str, Any]) -> tuple[list[str], list[str]]:
    callouts: list[str] = []
    recs: list[str] = []
    micro = summary.get("micro") or {}
    reg = micro.get("registry_load_all") or {}
    byn = micro.get("registry_by_name_x10") or {}
    if reg.get("mean_s") is not None and byn.get("mean_s") is not None:
        if byn["mean_s"] > max(0.005, (reg["mean_s"] or 0) * 2):
            callouts.append(
                f"Registry `by_name`×10 takes {byn['mean_s']:.4f}s vs load_all "
                f"{reg['mean_s']:.4f}s — by_name rescans YAMLs each call."
            )
            recs.append("Cache `model_registry.load_all()` results; make `by_name` O(1).")

    pf = micro.get("prompt_build_full") or {}
    pc = micro.get("prompt_build_correct") or {}
    if isinstance(pf.get("result"), dict) and isinstance(pc.get("result"), dict):
        full_c = pf["result"].get("chars") or 0
        cor_c = pc["result"].get("chars") or 0
        if full_c and cor_c:
            callouts.append(
                f"Prompt size: full={full_c} chars vs correct={cor_c} chars "
                f"(~{full_c / max(cor_c, 1):.1f}×)."
            )
            recs.append("Prefer `llm_mode=correct` for throughput once held-out gate passes.")

    pages = summary.get("pages") or {}
    h1 = pages.get("page_htr_only") or {}
    h2 = pages.get("page_htr_only_second") or {}
    if h1.get("timings") and h2.get("timings"):
        t1 = float(h1["timings"].get("htr") or h1.get("wall_s") or 0)
        t2 = float(h2["timings"].get("htr") or h2.get("wall_s") or 0)
        callouts.append(
            f"HTR-only page1={t1:.1f}s page2(same)={t2:.1f}s (model reload each call)."
        )
        if t1 > 0 and abs(t1 - t2) / t1 < 0.35:
            recs.append(
                "Cache Kraken HTR `.mlmodel` like lineation (`_get_model` + lock) "
                "to cut per-page load."
            )

    lin_c = pages.get("page_lineation_cold") or {}
    lin_r = pages.get("page_lineation_reuse") or {}
    if lin_c.get("timings") is not None and lin_r.get("timings") is not None:
        lc = float((lin_c.get("timings") or {}).get("lineation") or lin_c.get("wall_s") or 0)
        lr = float((lin_r.get("timings") or {}).get("lineation") or 0)
        callouts.append(f"Lineation cold≈{lc:.1f}s reuse≈{lr:.1f}s.")
        if lc > 2 and lr < lc * 0.25:
            recs.append("Keep `reuse_lines_xml=true` for retries; pre-lineate batches once.")

    corr = pages.get("page_llm_correct") or {}
    full = pages.get("page_llm_full") or {}
    if corr.get("timings") and full.get("timings"):
        cl = float((corr.get("timings") or {}).get("llm") or 0)
        fl = float((full.get("timings") or {}).get("llm") or 0)
        if cl and fl:
            callouts.append(f"LLM stage: correct={cl:.1f}s full={fl:.1f}s ({fl / cl:.1f}×).")
            recs.append("Correct mode is the main LLM wall-time lever; full mode only when needed.")
    elif corr.get("errors") or full.get("errors"):
        callouts.append(
            f"LLM page runs failed (correct errors={corr.get('errors')}; full={full.get('errors')})."
        )
        recs.append("Refresh Gemini API key or start Ollama for LLM stage timing.")

    batch = summary.get("batch") or {}
    b1 = batch.get("parallel_1") or {}
    b3 = batch.get("parallel_3") or {}
    if b1.get("wall_s") and b3.get("wall_s"):
        callouts.append(
            f"Batch HTR-only: p=1 wall {b1['wall_s']}s vs p=3 wall {b3['wall_s']}s "
            f"(eff {b3.get('efficiency_vs_serial')}×)."
        )
        if b3["wall_s"] < b1["wall_s"] * 0.7:
            recs.append(
                "Default `batch_parallel_pages=3` helps on CPU HTR; watch GPU VRAM contention."
            )
        else:
            recs.append(
                "Batch parallel gains weak — likely model-load or GIL/IO bound; cache HTR model first."
            )

    stylo = micro.get("stylo_analyze_text") or {}
    if stylo.get("mean_s") and stylo["mean_s"] > 5:
        callouts.append(f"Python stylo_analyze_text took {stylo['mean_s']:.1f}s on sample text.")
        recs.append("Run stylo once per manuscript (not per page); prefer pre-extracted whole text.")

    if not recs:
        recs.append("No high-ROI signal; expand page sample or enable LLM for fuller compare.")
    return callouts, recs


FLEET_SSH = {
    "halxvi": "hal-direct",
    "hal-direct": "hal-direct",
    "akdeniz": "akdeniz",
    "bridges2": "bridges2",
    "bridges_login": "bridges2",
}


def probe_one_ssh(host: str) -> dict[str, Any]:
    import subprocess

    script = r"""
set +e
echo HOST=$(hostname)
echo UNAME=$(uname -srm)
echo CPUS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null)
echo LOAD=$(uptime | sed 's/.*load average: //')
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null | head -1 | sed 's/^/GPU=/'
else
  echo GPU=none
fi
if [ -n "${SLURM_JOB_ID:-}" ]; then echo SLURM_JOB=$SLURM_JOB_ID PART=${SLURM_JOB_PARTITION:-}; fi
command -v sinfo >/dev/null && sinfo -p GPU-shared -o '%P %D %T %G' 2>/dev/null | head -8 | sed 's/^/SINFO=/'
ls ~/src/latin_documents/*.mlmodel 2>/dev/null | wc -l | awk '{print "MLMODELS="$1}'
ls ~/Projects/transcription-shell/src 2>/dev/null | head -1 | sed 's/^/TS=/'
test -d /ocean/projects/hum260002p/sstrickland/transcriber-shell && echo BRIDGES_PROJ=1
"""
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "ConnectTimeout=12",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                host,
                "bash",
                "-s",
            ],
            input=script,
            text=True,
            capture_output=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ssh": host, "ok": False, "error": str(exc)}
    lines = (proc.stdout or "").splitlines()
    data: dict[str, Any] = {"ssh": host, "ok": proc.returncode == 0, "raw": lines[-40:]}
    for line in lines:
        if "=" in line and not line.startswith(" "):
            k, _, v = line.partition("=")
            if k in ("HOST", "UNAME", "CPUS", "LOAD", "GPU", "MLMODELS", "TS", "BRIDGES_PROJ", "SLURM_JOB", "PART"):
                data[k.lower()] = v
    if host in ("bridges2",) or data.get("bridges_proj"):
        data["note"] = "login has no GPU; use GPU-shared sbatch for HTR/train"
    return data


def probe_fleet() -> dict[str, Any]:
    from transcriber_shell.runtime.machine_profile import (
        detect_machine_profile,
        load_fleet_yaml,
        recommend_settings,
        stage_routing_advice,
    )

    local = detect_machine_profile()
    rec = recommend_settings(local)
    out: dict[str, Any] = {
        "local": local.to_dict(),
        "local_recommend": rec,
        "routing": stage_routing_advice(local),
        "fleet_yaml": load_fleet_yaml(),
        "ssh": {},
    }
    for label, host in (("halxvi", "hal-direct"), ("akdeniz", "akdeniz"), ("bridges_login", "bridges2")):
        print(f"  probing {label} via {host}…", flush=True)
        out["ssh"][label] = probe_one_ssh(host)
    return out


def run_remote_htr_bench(ssh_host: str, *, force: bool = False) -> dict[str, Any]:
    """Rsync harness + one page pair; run HTR-only micro+page on remote; pull summary."""
    import subprocess
    import tempfile

    pairs = discover_page_pairs(1)
    if not pairs:
        return {"error": "no local page pairs to stage"}
    image, xml = pairs[0]

    # Skip busy fallback unless forced
    if ssh_host in ("hal-direct", "halxvi") and not force:
        probe = probe_one_ssh("hal-direct")
        load = probe.get("load") or ""
        try:
            load1 = float(str(load).split(",")[0].strip())
        except ValueError:
            load1 = 0.0
        cpus = int(probe.get("cpus") or "12")
        if load1 > cpus:
            return {
                "skipped": True,
                "reason": f"halxvi load1={load1} > cpus={cpus}; pass --force",
                "probe": probe,
            }

    remote_root = f"/tmp/ts-efficiency-{os.getpid()}"
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "stage"
        stage.mkdir()
        (stage / "page").mkdir()
        # Prefer small BM-LAT if present for faster remote HTR; else NYPL pair
        if BM_LAT.is_file():
            img_src = BM_LAT
            # remote will lineate if no xml — for skip-gm need xml; use NYPL pair
            img_src, xml_src = image, xml
        else:
            img_src, xml_src = image, xml
        subprocess.run(["cp", str(img_src), str(stage / "page" / img_src.name)], check=True)
        subprocess.run(["cp", str(xml_src), str(stage / "page" / xml_src.name)], check=True)

        print(f"  rsync harness → {ssh_host}:{remote_root}", flush=True)
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", ssh_host, f"mkdir -p {remote_root}"],
            check=False,
        )
        # Sync minimal: efficiency script + src package + fixture page
        for src, dest in (
            (REPO / "scripts/efficiency_run.py", f"{remote_root}/efficiency_run.py"),
            (REPO / "src/transcriber_shell", f"{remote_root}/transcriber_shell"),
            (REPO / "fixtures/prompt.example.yaml", f"{remote_root}/prompt.example.yaml"),
            (stage / "page", f"{remote_root}/page"),
        ):
            subprocess.run(
                [
                    "rsync",
                    "-az",
                    "-e",
                    "ssh -o BatchMode=yes -o ConnectTimeout=12",
                    f"{src}/" if src.is_dir() else str(src),
                    f"{ssh_host}:{dest}",
                ],
                check=False,
            )

        remote_cmd = f"""
set -e
cd {remote_root}
export PYTHONPATH={remote_root}:$PYTHONPATH
export TRANSCRIBER_SHELL_HTR_COMBINATION=kraken_htr_only
export TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken
export TRANSCRIBER_SHELL_AUTO_EFFICIENCY=1
PYBIN=""
for c in "$HOME/.venv-kraken/bin/python" "$HOME/kraken-venv/bin/python" "$HOME/Projects/transcription-shell/.venv/bin/python" python3; do
  if [ -x "$c" ] || command -v "$c" >/dev/null 2>&1; then
    if "$c" -c "import importlib.util as u; import sys; sys.exit(0 if u.find_spec('kraken') else 1)" 2>/dev/null; then
      PYBIN="$c"
      break
    fi
  fi
done
if [ -z "$PYBIN" ]; then PYBIN=python3; fi
echo "PYBIN=$PYBIN"
# models
for d in $HOME/src/latin_documents $HOME/Projects/transcription-shell; do
  if [ -f $d/gm-htr-computus_best.mlmodel ]; then
    export TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=$d/gm-htr-computus_best.mlmodel
  fi
  if [ -f $d/kraken-merged-seg.mlmodel_best.mlmodel ]; then
    export TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH=$d/kraken-merged-seg.mlmodel_best.mlmodel
  fi
done
IMG=$(ls page/*.jpg page/*.png 2>/dev/null | head -1)
XML=$(ls page/*.xml 2>/dev/null | head -1)
"$PYBIN" - <<PY
import json, os, time
from pathlib import Path
import sys
sys.path.insert(0, "{remote_root}")
from transcriber_shell.runtime.machine_profile import detect_machine_profile, recommend_settings
from transcriber_shell.config import Settings
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.run import run_pipeline
import yaml

prof = detect_machine_profile()
rec = recommend_settings(prof)
img = Path("$IMG")
xml = Path("$XML") if "$XML" else None
prompt = yaml.safe_load(Path("prompt.example.yaml").read_text())
art = Path("artifacts"); art.mkdir(exist_ok=True)
s = Settings(
    artifacts_dir=art,
    llm_mode="off",
    htr_combination="kraken_htr_only",
    lineation_backend="kraken",
    reuse_lines_xml=True,
)
if os.environ.get("TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH"):
    s = s.model_copy(update={{"kraken_htr_model_path": Path(os.environ["TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH"])}})
job = TranscribeJob(job_id="eff-remote", image_path=img, prompt_cfg=prompt, provider="gemini")
t0 = time.perf_counter()
res = run_pipeline(job, skip_gm=xml is not None and xml.is_file(), lines_xml_path=xml if xml and xml.is_file() else None, settings=s)
wall = time.perf_counter() - t0
out = {{
  "profile": prof.to_dict(),
  "recommend": rec,
  "wall_s": round(wall, 3),
  "timings": dict(res.timings or []),
  "ok": not res.errors,
  "errors": list(res.errors or [])[:5],
  "image": str(img),
}}
Path("remote_summary.json").write_text(json.dumps(out, indent=2))
print(json.dumps({{"wall_s": out["wall_s"], "timings": out["timings"], "ok": out["ok"], "alias": prof.alias}}))
PY
"""
        print(f"  running remote HTR-only on {ssh_host}…", flush=True)
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", ssh_host, "bash", "-s"],
            input=remote_cmd,
            text=True,
            capture_output=True,
            timeout=3600,
        )
        local_out = REPO / "benchmark/results/efficiency" / "_work" / f"remote_{ssh_host.replace('.', '_')}"
        local_out.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "rsync",
                "-az",
                "-e",
                "ssh -o BatchMode=yes",
                f"{ssh_host}:{remote_root}/remote_summary.json",
                str(local_out / "remote_summary.json"),
            ],
            check=False,
        )
        summary_path = local_out / "remote_summary.json"
        payload: dict[str, Any] = {
            "ssh": ssh_host,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
        if summary_path.is_file():
            payload["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            payload["error"] = "remote_summary.json missing"
        return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--micro-only", action="store_true")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--skip-lineation", action="store_true")
    ap.add_argument("--skip-batch", action="store_true")
    ap.add_argument("--batch-pages", type=int, default=3)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--probe-fleet",
        action="store_true",
        help="Probe local + SSH fleet (halxvi/akdeniz/bridges login); write fleet_probe.json",
    )
    ap.add_argument(
        "--remote",
        metavar="HOST",
        default=None,
        help="Run HTR-only efficiency on SSH host (akdeniz|hal-direct). Skips local page suite.",
    )
    ap.add_argument("--force", action="store_true", help="Allow remote bench on busy halxvi")
    ap.add_argument(
        "--local-micro",
        action="store_true",
        help="With --probe-fleet / --remote, also run local microbenches",
    )
    args = ap.parse_args()

    env_latin = REPO / "scripts/latin_ms/.env.latin-ms"
    if env_latin.is_file():
        for line in env_latin.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "GOOGLE_API_KEY" and v.startswith("AIza"):
                os.environ["GOOGLE_API_KEY"] = v
            elif k not in os.environ:
                os.environ[k] = v

    stamp = _now_stamp()
    out_dir = args.out or (REPO / "benchmark/results/efficiency" / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "stamp": stamp,
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "backends": {
            "htr_model": str(HTR_COMPUTUS) if HTR_COMPUTUS.is_file() else None,
            "seg_model": str(SEG_MODEL) if SEG_MODEL.is_file() else None,
            "stylo_ref": str(STYLO_REF) if STYLO_REF.is_dir() else None,
            "google_api_key": (
                "AIza…"
                if (os.environ.get("GOOGLE_API_KEY") or "").startswith("AIza")
                else "missing"
            ),
            "nypl_pairs": len(discover_page_pairs(99)),
        },
    }

    if args.probe_fleet:
        print("== probe fleet ==", flush=True)
        try:
            summary["fleet"] = probe_fleet()
            (out_dir / "fleet_probe.json").write_text(
                json.dumps(summary["fleet"], indent=2), encoding="utf-8"
            )
            print(f"wrote {out_dir / 'fleet_probe.json'}", flush=True)
        except Exception as exc:  # noqa: BLE001
            summary["fleet"] = {"error": str(exc), "trace": traceback.format_exc()}

    if args.remote:
        host = FLEET_SSH.get(args.remote, args.remote)
        print(f"== remote HTR bench ({host}) ==", flush=True)
        try:
            summary["remote"] = run_remote_htr_bench(host, force=args.force)
        except Exception as exc:  # noqa: BLE001
            summary["remote"] = {"error": str(exc), "trace": traceback.format_exc()}
        if not args.local_micro and not args.probe_fleet:
            # still write routing from local detect
            try:
                from transcriber_shell.runtime.machine_profile import (
                    detect_machine_profile,
                    stage_routing_advice,
                )

                summary.setdefault("fleet", {})
                summary["fleet"]["local"] = detect_machine_profile().to_dict()
                summary["fleet"]["routing"] = stage_routing_advice()
            except Exception:  # noqa: BLE001
                pass
            callouts, recs = derive_callouts(summary)
            summary["callouts"] = callouts
            summary["recommendations"] = recs
            _finalize_report(summary, out_dir)
            return 0

    run_local = (not args.remote and not args.probe_fleet) or args.local_micro or args.micro_only
    if args.probe_fleet and not args.local_micro and not args.remote and not args.micro_only:
        # probe-only default
        run_local = False

    if run_local or args.micro_only:
        print("== microbenches ==", flush=True)
        try:
            summary["micro"] = bench_micro()
        except Exception as exc:  # noqa: BLE001
            summary["micro"] = {"error": str(exc), "trace": traceback.format_exc()}
            print("micro failed:", exc, flush=True)

    if run_local and not args.micro_only and not args.remote:
        print("== page suites ==", flush=True)
        try:
            summary["pages"] = bench_pages(
                skip_llm=args.skip_llm,
                include_lineation=not args.skip_lineation,
            )
        except Exception as exc:  # noqa: BLE001
            summary["pages"] = {"error": str(exc), "trace": traceback.format_exc()}
            print("pages failed:", exc, flush=True)

        if not args.skip_batch:
            print("== batch parallel ==", flush=True)
            summary["batch"] = {}
            try:
                summary["batch"]["parallel_1"] = bench_batch(args.batch_pages, 1)
                summary["batch"]["parallel_3"] = bench_batch(args.batch_pages, 3)
            except Exception as exc:  # noqa: BLE001
                summary["batch"]["error"] = str(exc)
                summary["batch"]["trace"] = traceback.format_exc()

    callouts, recs = derive_callouts(summary)
    # Fleet routing callouts
    fleet = summary.get("fleet") or {}
    if fleet.get("routing"):
        callouts.append(
            "Same pipeline on every host; pick akdeniz (interactive) or Bridges "
            "GPU-shared (batch) for speed — Settings differ via --auto-efficiency."
        )
    remote = summary.get("remote") or {}
    if isinstance(remote.get("summary"), dict):
        rs = remote["summary"]
        callouts.append(
            f"Remote {remote.get('ssh')} HTR wall={rs.get('wall_s')}s timings={rs.get('timings')}"
        )
        recs.append("Prefer akdeniz for interactive Kraken HTR; cache mlmodel across pages.")
    summary["callouts"] = callouts
    summary["recommendations"] = recs
    _finalize_report(summary, out_dir)
    return 0


def _finalize_report(summary: dict[str, Any], out_dir: Path) -> None:
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = write_report(summary, out_dir)
    # Append fleet routing section
    fleet = summary.get("fleet") or {}
    extra: list[str] = []
    if fleet.get("routing"):
        extra += ["", "## Recommended stage routing", ""]
        extra += ["| Stage | Preferred | Fallback |", "|---|---|---|"]
        for r in fleet["routing"]:
            extra.append(
                f"| {r.get('stage')} | {r.get('preferred')} | {r.get('fallback')} |"
            )
    if summary.get("remote"):
        extra += ["", "## Remote HTR", "", "```json", json.dumps(summary["remote"], indent=2)[:4000], "```"]
    if extra:
        with report.open("a", encoding="utf-8") as f:
            f.write("\n".join(extra) + "\n")
    print(f"wrote {out_dir / 'summary.json'}", flush=True)
    print(f"wrote {report}", flush=True)
    print("\n".join(f"- {c}" for c in (summary.get("callouts") or [])), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
