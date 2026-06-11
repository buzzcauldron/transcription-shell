#!/usr/bin/env python3
"""Analyze blind stress-test results and emit a prioritized HTR training plan.

Reads shell-pipeline accuracy from benchmark/test-results/stress/ and maps
weaknesses to corpus filters + sbatch jobs (see blind_test_targets.yaml).

Usage (from repo root):
  python scripts/blind_test_training_plan.py
  python scripts/blind_test_training_plan.py --stress-dir vendor/transcription-protocol/benchmark/test-results/stress
  python scripts/blind_test_training_plan.py --write-json artifacts/blind-test-training/plan.json

Ground-truth benchmark strings are never used as training labels — only for
scoring. Training actions point at existing line-level PAGE XML in gt-mss/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
PROTO = REPO / "vendor" / "transcription-protocol"
DEFAULT_STRESS = PROTO / "benchmark" / "test-results" / "stress"
DEFAULT_TARGETS = REPO / "scripts" / "blind_test_targets.yaml"


def _load_evaluator():
    sys.path.insert(0, str(PROTO))
    from benchmark.parse_transcript import get_transcription_root, parse_transcription_yaml
    from benchmark.stress_metrics import run_evaluator

    return parse_transcription_yaml, get_transcription_root, run_evaluator


def shell_accuracy_for_case(stress_dir: Path, case_id: str, evaluator: str) -> list[dict]:
    parse_yaml, get_root, run_eval = _load_evaluator()
    case_path = stress_dir / case_id
    if not case_path.is_dir():
        return []

    rows = []
    for sub in sorted(case_path.iterdir()):
        if not sub.name.startswith("shell-"):
            continue
        resp = sub / "response.txt"
        if not resp.is_file():
            continue
        raw = resp.read_text(encoding="utf-8")
        htr_key = sub.name.removeprefix("shell-").rsplit("-", 1)[0]
        if raw.startswith("ERROR:"):
            rows.append({"htr": htr_key, "accuracy": None, "additions": None, "omissions": None, "error": raw[:120]})
            continue
        data, err = parse_yaml(raw)
        if err:
            rows.append({"htr": htr_key, "accuracy": None, "additions": None, "omissions": None, "error": err[:120]})
            continue
        root_out, rerr = get_root(data)
        if rerr:
            rows.append({"htr": htr_key, "accuracy": None, "additions": None, "omissions": None, "error": rerr[:120]})
            continue
        segs = root_out.get("segments") or []
        m = run_eval(evaluator, segs)
        if m.get("error"):
            rows.append({"htr": htr_key, "accuracy": None, "additions": None, "omissions": None, "error": m["error"][:120]})
            continue
        rows.append(
            {
                "htr": htr_key,
                "accuracy": m.get("accuracy_percent"),
                "additions": m.get("addition_count"),
                "omissions": m.get("omission_count"),
                "disposition": m.get("disposition"),
            }
        )
    return rows


def image_only_best(stress_dir: Path, case_id: str, evaluator: str) -> float | None:
    parse_yaml, get_root, run_eval = _load_evaluator()
    case_path = stress_dir / case_id
    if not case_path.is_dir():
        return None
    best = None
    for sub in case_path.iterdir():
        if sub.name.startswith("shell-"):
            continue
        resp = sub / "response.txt"
        if not resp.is_file():
            continue
        raw = resp.read_text(encoding="utf-8")
        if raw.startswith("ERROR:"):
            continue
        data, err = parse_yaml(raw)
        if err:
            continue
        root_out, rerr = get_root(data)
        if rerr:
            continue
        m = run_eval(evaluator, root_out.get("segments") or [])
        acc = m.get("accuracy_percent")
        if acc is not None and (best is None or acc > best):
            best = acc
    return best


def build_plan(*, stress_dir: Path, targets_path: Path) -> dict:
    targets = yaml.safe_load(targets_path.read_text(encoding="utf-8"))
    cases_cfg = targets.get("cases") or {}
    gap_thr = float(targets.get("htr_retrain_gap_threshold", 3.0))
    solved_thr = float(targets.get("htr_solved_threshold", 90.0))

    priorities: list[dict] = []

    for case_id, tcfg in cases_cfg.items():
        evaluator = tcfg.get("evaluator", "lincoln")
        shell_rows = shell_accuracy_for_case(stress_dir, case_id, evaluator)
        scored = [r for r in shell_rows if r.get("accuracy") is not None]
        if not scored:
            priorities.append(
                {
                    "case": case_id,
                    "label": tcfg.get("label", case_id),
                    "priority": "skip",
                    "reason": "no scored shell runs",
                    "training": _training_block(tcfg),
                }
            )
            continue

        best_shell = max(scored, key=lambda r: r["accuracy"])
        worst_shell = min(scored, key=lambda r: r["accuracy"])
        img_best = image_only_best(stress_dir, case_id, evaluator)
        best_acc = best_shell["accuracy"]
        gap = (img_best - best_acc) if img_best is not None else None

        train_corpora = tcfg.get("train_corpora") or []
        has_corpus = len(train_corpora) > 0
        sbatch = tcfg.get("sbatch")

        if best_acc >= solved_thr:
            priority = "low"
            reason = f"shell already {best_acc:.1f}% (≥{solved_thr}%)"
        elif not has_corpus:
            priority = "blocked"
            reason = "no line-level training corpus registered for this script/language"
        elif gap is not None and gap < gap_thr and best_acc >= (img_best or 0) - 1:
            priority = "medium"
            reason = f"shell {best_acc:.1f}% within {gap_thr}pt of image-only; LLM/schema may dominate"
        else:
            priority = "high"
            reason = f"shell best {best_acc:.1f}% ({best_shell['htr']}); image-only {img_best or 0:.1f}%"

        priorities.append(
            {
                "case": case_id,
                "label": tcfg.get("label", case_id),
                "priority": priority,
                "reason": reason,
                "shell_runs": shell_rows,
                "best_shell": best_shell,
                "worst_shell": worst_shell,
                "image_only_best_pct": img_best,
                "gap_image_minus_shell": round(gap, 2) if gap is not None else None,
                "training": _training_block(tcfg),
                "commands": _commands_for_case(case_id, tcfg, priority),
            }
        )

    order = {"high": 0, "medium": 1, "low": 2, "blocked": 3, "skip": 4}
    def _sort_key(p: dict) -> tuple:
        acc = (p.get("best_shell") or {}).get("accuracy")
        return (order.get(p["priority"], 9), -(acc if acc is not None else -1))

    priorities.sort(key=_sort_key)

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stress_dir": str(stress_dir),
        "thresholds": {"htr_retrain_gap": gap_thr, "htr_solved": solved_thr},
        "priorities": priorities,
    }


def _training_block(tcfg: dict) -> dict:
    return {
        "script": tcfg.get("script"),
        "base_model": tcfg.get("base_model"),
        "output_model": tcfg.get("output_model"),
        "train_corpora": tcfg.get("train_corpora"),
        "val_corpora": tcfg.get("val_corpora"),
        "metadata_filter": tcfg.get("metadata_filter"),
        "sbatch": tcfg.get("sbatch"),
        "notes": (tcfg.get("notes") or "").strip(),
    }


def _commands_for_case(case_id: str, tcfg: dict, priority: str) -> list[str]:
    if priority in ("skip", "low", "blocked"):
        return []
    cmds = [
        f"python scripts/build_weakness_manifest.py --case {case_id}",
    ]
    sbatch = tcfg.get("sbatch")
    if sbatch:
        cmds.append(f"# On Bridges (after corpus prep + GT rsync):")
        if sbatch.endswith("r_blind_weakness_finetune.sbatch"):
            cmds.append(f"BLIND_CASE={case_id} sbatch {sbatch}")
        else:
            cmds.append(f"sbatch {sbatch}")
    cmds.append(
        f"bash scripts/pull_bridges_htr_models.sh  # after training completes"
    )
    cmds.append(
        f".venv/bin/python scripts/stress_shell_run.py --include-optional --cases {case_id} --all-htr"
    )
    return cmds


def write_markdown(plan: dict, path: Path) -> None:
    lines = [
        "# Blind-test training plan",
        "",
        f"Generated: {plan['generated']} (UTC)",
        "",
        "Prioritized HTR retraining from shell-pipeline blind stress results.",
        "Benchmark GT is scoring-only; training uses line PAGE XML from `gt-mss/`.",
        "",
    ]
    for p in plan["priorities"]:
        lines.append(f"## {p['case']} — {p['label']}")
        lines.append(f"- **Priority:** {p['priority']}")
        lines.append(f"- **Reason:** {p['reason']}")
        best = p.get("best_shell") or {}
        if best.get("accuracy") is not None:
            lines.append(
                f"- **Best shell:** {best.get('htr')} @ {best['accuracy']:.1f}% "
                f"({best.get('additions')} add / {best.get('omissions')} omit)"
            )
        if p.get("image_only_best_pct") is not None:
            lines.append(f"- **Image-only best:** {p['image_only_best_pct']:.1f}%")
        tr = p.get("training") or {}
        if tr.get("sbatch"):
            lines.append(f"- **Sbatch:** `{tr['sbatch']}`")
        if tr.get("train_corpora"):
            lines.append(f"- **Train corpora:** {', '.join(tr['train_corpora'])}")
        if tr.get("notes"):
            lines.append(f"- **Notes:** {tr['notes']}")
        cmds = p.get("commands") or []
        if cmds:
            lines.append("- **Commands:**")
            lines.append("```bash")
            lines.extend(cmds)
            lines.append("```")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Blind stress → HTR training plan")
    ap.add_argument("--stress-dir", type=Path, default=DEFAULT_STRESS)
    ap.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    ap.add_argument("--write-json", type=Path, default=REPO / "artifacts" / "blind-test-training" / "plan.json")
    ap.add_argument("--write-md", type=Path, default=REPO / "artifacts" / "blind-test-training" / "plan.md")
    ap.add_argument("--print-json", action="store_true")
    args = ap.parse_args()

    if not args.stress_dir.is_dir():
        print(f"Stress dir missing: {args.stress_dir}", file=sys.stderr)
        print("Run: .venv/bin/python scripts/stress_shell_run.py --include-optional --all-htr", file=sys.stderr)
        return 1

    plan = build_plan(stress_dir=args.stress_dir, targets_path=args.targets)
    args.write_json.parent.mkdir(parents=True, exist_ok=True)
    args.write_json.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    write_markdown(plan, args.write_md)

    print(f"[plan] {args.write_json}")
    print(f"[plan] {args.write_md}")
    for p in plan["priorities"]:
        best = (p.get("best_shell") or {}).get("accuracy")
        acc_s = f"{best:.1f}%" if best is not None else "—"
        print(f"  {p['priority']:8} {p['case']:16} shell={acc_s}  {p['reason']}")

    if args.print_json:
        print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
