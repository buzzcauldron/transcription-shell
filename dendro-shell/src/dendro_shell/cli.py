"""dendro CLI: open | detect | train | export | crossdate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_open(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("UI extra required: pip install -e '.[ui]'", file=sys.stderr)
        return 1
    from dendro_shell.ui.app import create_app

    app = create_app(open_image=args.image, library_dir=args.library)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    from dendro_shell.pipeline import export_all, run_detect
    from dendro_shell.project import Point

    pith = None
    if args.pith:
        x, y = args.pith.split(",")
        pith = Point(x=float(x), y=float(y))

    project = run_detect(
        args.image,
        method=args.method,
        preset=args.preset,
        sample_type=args.type,
        pith=pith,
        angle_deg=args.angle,
        min_distance_px=args.min_distance,
        prominence=args.prominence,
        outer_year=args.outer_year,
        sample_code=args.sample_code or Path(args.image).stem,
        auto=True,
    )
    out = Path(args.output or (Path(args.image).parent / "dendro_out"))
    paths = export_all(project, out)
    print(json.dumps(paths, indent=2))
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    from dendro_shell.train.job import TrainConfig, get_train_status, run_training

    cfg = TrainConfig(
        library_dir=args.project_dir or args.library,
        name=args.name,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch_size=args.batch,
        lr=args.lr,
        augment=not args.no_augment,
        device=args.device,
        species=args.species,
        tag=args.tag,
        fine_tune=not args.no_finetune,
        activate=not args.no_activate,
        overwrite=args.overwrite,
    )

    def on_prog(st):
        print(
            f"[{st.state}] epoch {st.epoch}/{st.epochs} loss={st.loss:.4f} "
            f"dice={st.val_dice:.3f} f1={st.val_f1:.3f} {st.message}",
            flush=True,
        )

    st = run_training(cfg, progress_cb=on_prog, background=False)
    if st.state == "error":
        print(st.message, file=sys.stderr)
        return 1
    print(json.dumps(st.to_dict(), indent=2))
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from dendro_shell.pipeline import export_all
    from dendro_shell.project import Project

    project = Project.load(args.project)
    out = Path(args.output or Path(args.project).parent)
    print(json.dumps(export_all(project, out), indent=2))
    return 0


def _cmd_crossdate(args: argparse.Namespace) -> int:
    from dendro_shell.crossdate import correlate_against_reference
    from dendro_shell.project import Project
    from dendro_shell.series import build_width_series

    project = Project.load(args.project)
    series = build_width_series(project)
    hits = correlate_against_reference(
        series,
        args.reference,
        min_overlap=args.min_overlap,
        max_lag=args.max_lag,
    )
    payload = [
        {
            "lag": h.lag,
            "correlation": h.correlation,
            "overlap": h.overlap,
            "reference_id": h.reference_id,
        }
        for h in hits[: args.top]
    ]
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_library_add(args: argparse.Namespace) -> int:
    from dendro_shell.project import Project
    from dendro_shell.train.dataset import add_project_to_library

    project = Project.load(args.project)
    dest = add_project_to_library(project, args.library, name=args.name)
    print(dest)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dendro",
        description="Path-first tree-ring tracing, chronology export, in-app training",
    )
    sub = p.add_subparsers(dest="command", required=True)

    open_p = sub.add_parser("open", help="Launch browser UI")
    open_p.add_argument("image", nargs="?", help="Optional image to open")
    open_p.add_argument("--host", default="127.0.0.1")
    open_p.add_argument("--port", type=int, default=8765)
    open_p.add_argument("--library", default=None, help="Training library directory")
    open_p.set_defaults(func=_cmd_open)

    det = sub.add_parser("detect", help="Detect rings along default/auto path")
    det.add_argument("image")
    det.add_argument("-o", "--output", default=None)
    det.add_argument("--method", choices=["classical", "unet"], default="classical")
    det.add_argument("--preset", default="auto", help="Preprocess preset or 'auto'")
    det.add_argument("--type", choices=["core", "disc", "auto"], default="auto")
    det.add_argument("--pith", default=None, help="x,y pith for discs")
    det.add_argument("--angle", type=float, default=0.0, help="Diameter angle for discs")
    det.add_argument("--min-distance", type=float, default=None, help="Min peak spacing (adaptive if omitted)")
    det.add_argument("--prominence", type=float, default=None, help="Peak prominence (adaptive if omitted)")
    det.add_argument("--outer-year", type=int, default=None)
    det.add_argument("--sample-code", default="")
    det.set_defaults(func=_cmd_detect)

    tr = sub.add_parser("train", help="Train U-Net from library (same runner as UI)")
    tr.add_argument("--project-dir", default=None, help="Library directory (alias)")
    tr.add_argument("--library", default=None)
    tr.add_argument("--name", default="boundary_unet")
    tr.add_argument("--epochs", type=int, default=30)
    tr.add_argument("--imgsz", type=int, default=512)
    tr.add_argument("--batch", type=int, default=2)
    tr.add_argument("--lr", type=float, default=1e-3)
    tr.add_argument("--device", default="auto")
    tr.add_argument("--species", default=None)
    tr.add_argument("--tag", default=None)
    tr.add_argument("--no-augment", action="store_true")
    tr.add_argument("--no-finetune", action="store_true")
    tr.add_argument("--no-activate", action="store_true")
    tr.add_argument("--overwrite", action="store_true")
    tr.set_defaults(func=_cmd_train)

    ex = sub.add_parser("export", help="Export rwl/pos/overlay from project.json")
    ex.add_argument("project")
    ex.add_argument("-o", "--output", default=None)
    ex.set_defaults(func=_cmd_export)

    cd = sub.add_parser("crossdate", help="Correlate series vs reference .rwl")
    cd.add_argument("project")
    cd.add_argument("reference")
    cd.add_argument("--min-overlap", type=int, default=30)
    cd.add_argument("--max-lag", type=int, default=20)
    cd.add_argument("--top", type=int, default=10)
    cd.set_defaults(func=_cmd_crossdate)

    lib = sub.add_parser("library-add", help="Add project.json to training library")
    lib.add_argument("project")
    lib.add_argument("--library", default=None)
    lib.add_argument("--name", default=None)
    lib.set_defaults(func=_cmd_library_add)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
