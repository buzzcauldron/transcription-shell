#!/usr/bin/env python3
"""Clear false harvest completion stamps so HTR can actually run.

Removes ``status/pipeline.DONE`` (and matching supervisor ``*.done`` files) when
YAML+skip coverage is below 90%. Deletes ``.failed`` markers so retryable
infrastructure failures (Mac model paths, LLM/Ollama wall) are not treated as
terminal. Writes ``status/skip_print_dump`` for Google Books / Notices dumps.

Does not delete images, YAML, or ``.skipped`` markers.

Usage (on Akdeniz):
  python3 scripts/computus/reset_false_pipeline_done.py --jobs-root /mnt/constantinople/seth/latin-ms-workspace/jobs
  python3 scripts/computus/reset_false_pipeline_done.py --jobs-root ... --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htr_watch_policy import (  # noqa: E402
    job_is_doneish,
    looks_like_print_dump,
    sample_image_names,
)


def _unlink(path: Path, apply: bool) -> bool:
    if not path.exists():
        return False
    if apply:
        path.unlink()
    return True


def _rm_failed(art: Path, apply: bool) -> int:
    n = 0
    if not art.is_dir():
        return 0
    for p in art.rglob(".failed"):
        if p.is_file():
            n += 1
            if apply:
                p.unlink()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-root", type=Path, required=True)
    ap.add_argument(
        "--state-dir",
        type=Path,
        action="append",
        default=[],
        help="Supervisor state dirs whose <job_id>.done files should be cleared",
    )
    ap.add_argument("--apply", action="store_true", help="Perform deletions (default: dry-run)")
    args = ap.parse_args()
    jobs = args.jobs_root
    if not jobs.is_dir():
        print(f"missing jobs-root {jobs}", file=sys.stderr)
        return 2

    n_false = n_print = n_ok = n_failed = 0
    for job in sorted(jobs.iterdir()):
        if not job.is_dir():
            continue
        stamp = job / "status" / "pipeline.DONE"
        htr_stamp = job / "status" / "htr.DONE"
        names = sample_image_names(job)
        if looks_like_print_dump(job.name, names):
            n_print += 1
            skip = job / "status" / "skip_print_dump"
            if args.apply:
                skip.parent.mkdir(parents=True, exist_ok=True)
                skip.write_text("google-books or notices-et-extraits dump; not manuscript HTR\n")
            print(f"PRINT_DUMP {job.name}")
            continue
        if not stamp.is_file() and not htr_stamp.is_file():
            # Still clear .failed on incomplete jobs that never got a stamp
            art = job / "03_artifacts_2500"
            if art.is_dir() and any(art.rglob(".failed")):
                if not job_is_doneish(job):
                    nf = _rm_failed(art, args.apply)
                    n_failed += nf
                    print(f"CLEAR_FAILED {job.name} failed={nf}")
            continue
        if job_is_doneish(job):
            n_ok += 1
            continue
        n_false += 1
        nf = _rm_failed(job / "03_artifacts_2500", args.apply)
        n_failed += nf
        removed = []
        if _unlink(stamp, args.apply):
            removed.append("pipeline.DONE")
        if htr_stamp.is_file() and not job_is_doneish(job) and _unlink(htr_stamp, args.apply):
            removed.append("htr.DONE")
        for state in args.state_dir:
            if _unlink(state / f"{job.name}.done", args.apply):
                removed.append(f"state:{state.name}")
        print(f"FALSE_DONE {job.name} cleared={','.join(removed) or '(dry)'} failed={nf}")

    mode = "APPLY" if args.apply else "DRY"
    print(
        f"{mode} false_done={n_false} print_dump={n_print} "
        f"true_doneish={n_ok} failed_markers={n_failed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
