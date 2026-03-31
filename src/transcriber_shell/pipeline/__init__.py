"""Batch and single-image pipeline entrypoints.

The usual flow is `run_pipeline`: one image + prompt → artifacts. See `docs/simple-workflow.md`.
"""

from transcriber_shell.pipeline.batch import discover_images, run_batch, write_batch_report
from transcriber_shell.pipeline.run import (
    load_prompt_cfg,
    load_prompt_cfg_from_str,
    run_pipeline,
)

__all__ = [
    "discover_images",
    "load_prompt_cfg",
    "load_prompt_cfg_from_str",
    "run_batch",
    "run_pipeline",
    "write_batch_report",
]
