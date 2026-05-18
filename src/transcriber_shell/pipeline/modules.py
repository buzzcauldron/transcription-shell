"""Pipeline module interface and shared context (Phase 4 scaffold).

This is the type foundation for the modular redesign described in
``docs/tool-redesign.md``. Nothing in the pipeline imports from here yet —
``run_pipeline`` is still the single orchestrator. As stages are extracted
(starting with lineation, HTR, LLM-correct, output), each is implemented as a
``PipelineModule`` and added to the ``DEFAULT_MODULES`` list.

The GUI will eventually iterate ``DEFAULT_MODULES`` to render one row per
module — see ``docs/tool-redesign.md`` § GUI shape.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from transcriber_shell.config import Settings
from transcriber_shell.htr.base import HtrResult
from transcriber_shell.models.job import TranscribeJob


@dataclass
class Context:
    """Per-job state passed between modules.

    Mutated in place by each module; the orchestrator inspects ``errors`` after
    each step to decide whether to short-circuit.
    """

    job: TranscribeJob
    settings: Settings
    lines_xml_path: Path | None = None
    text_line_count: int = 0
    htr_drafts: dict[str, HtrResult | Exception] = field(default_factory=dict)
    htr_future: Future | None = None  # set when HTR runs alongside LLM
    htr_executor: ThreadPoolExecutor | None = None
    language: str | None = None
    transcription_text: str | None = None
    transcription_yaml_path: Path | None = None
    llm_usage: dict[str, int] | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timings: list[tuple[str, float]] = field(default_factory=list)
    log_fn: Any = None  # Callable[[str], None] | None

    def log(self, msg: str) -> None:
        if self.log_fn is not None:
            self.log_fn(msg)


@runtime_checkable
class PipelineModule(Protocol):
    """A single composable pipeline stage.

    Implementations must be **idempotent** for a given ``Context`` snapshot —
    calling ``run`` twice with the same input must produce the same result
    (modulo timing). This is what makes per-module retry safe.

    ``applies(ctx)`` is a cheap precondition check; the orchestrator skips
    modules whose preconditions aren't met (e.g. ``llm-correct`` doesn't apply
    when ``ctx.htr_drafts`` is empty).
    """

    name: str

    def applies(self, ctx: Context) -> bool: ...
    def run(self, ctx: Context) -> Context: ...


# ── Module registry ────────────────────────────────────────────────────────
# Populated as stages are extracted from ``pipeline.run``. Order matters: the
# orchestrator iterates this list in sequence.

DEFAULT_MODULES: list[PipelineModule] = []
