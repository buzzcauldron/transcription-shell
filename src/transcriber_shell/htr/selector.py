"""Select how Glyph Machina HTR, Zenodo (kraken) HTR, and LLM-only shell combine.

Glyph Machina HTR is treated as the primary recognition assist; Zenodo kraken-htr
as secondary. ``shell`` means the original transcriber-shell path: LLM only,
with no HTR backend calls (lineation unchanged).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from transcriber_shell.config import Settings
from transcriber_shell.htr.base import HtrResult


class HtrPlanKind(str, Enum):
    NONE = "none"
    WITH_LLM_PARALLEL = "with_llm_parallel"
    BEFORE_LLM_PARALLEL = "before_llm_parallel"
    BEFORE_LLM_ORDERED = "before_llm_ordered"


@dataclass(frozen=True)
class HtrExecutionPlan:
    """Resolved HTR step for one pipeline run."""

    kind: HtrPlanKind
    tasks: dict[str, Callable[[], HtrResult]] | None = None
    ordered: list[tuple[str, Callable[[], HtrResult]]] | None = None


def _effective_combination(s: "Settings") -> str:
    raw = (s.htr_combination or "default").strip().lower()
    if raw == "default":
        return "parallel" if s.htr_parallel else "sequential"
    return raw


def plan_htr_execution(
    s: "Settings",
    all_tasks: dict[str, Callable[[], HtrResult]],
) -> HtrExecutionPlan:
    """Map settings + built tasks to an execution plan (may be NONE)."""
    c = _effective_combination(s)

    if c in ("off", "shell", "none", "llm_only"):
        if all_tasks:
            # Tasks are configured — run them sequentially before LLM regardless of combination opt-out.
            return HtrExecutionPlan(kind=HtrPlanKind.BEFORE_LLM_PARALLEL, tasks=dict(all_tasks))
        return HtrExecutionPlan(kind=HtrPlanKind.NONE)

    if c in ("kraken_htr", "zenodo"):
        tasks = {k: v for k, v in all_tasks.items() if k == "kraken-htr"}
        if not tasks:
            return HtrExecutionPlan(kind=HtrPlanKind.NONE)
        return HtrExecutionPlan(kind=HtrPlanKind.BEFORE_LLM_PARALLEL, tasks=tasks)

    if c in ("gm_htr", "glyph_machina", "gm"):
        tasks = {k: v for k, v in all_tasks.items() if k == "gm-htr"}
        if not tasks:
            return HtrExecutionPlan(kind=HtrPlanKind.NONE)
        return HtrExecutionPlan(kind=HtrPlanKind.BEFORE_LLM_PARALLEL, tasks=tasks)

    if c == "parallel":
        if not all_tasks:
            return HtrExecutionPlan(kind=HtrPlanKind.NONE)
        return HtrExecutionPlan(kind=HtrPlanKind.WITH_LLM_PARALLEL, tasks=dict(all_tasks))

    if c == "sequential":
        if not all_tasks:
            return HtrExecutionPlan(kind=HtrPlanKind.NONE)
        return HtrExecutionPlan(kind=HtrPlanKind.BEFORE_LLM_PARALLEL, tasks=dict(all_tasks))

    if c in ("gm_then_kraken", "gm_then_zenodo", "best_then_second"):
        ordered: list[tuple[str, Callable[[], HtrResult]]] = []
        if "gm-htr" in all_tasks:
            ordered.append(("gm-htr", all_tasks["gm-htr"]))
        if "kraken-htr" in all_tasks:
            ordered.append(("kraken-htr", all_tasks["kraken-htr"]))
        if not ordered:
            return HtrExecutionPlan(kind=HtrPlanKind.NONE)
        if len(ordered) == 1:
            k, fn = ordered[0]
            return HtrExecutionPlan(
                kind=HtrPlanKind.BEFORE_LLM_PARALLEL, tasks={k: fn}
            )
        return HtrExecutionPlan(kind=HtrPlanKind.BEFORE_LLM_ORDERED, ordered=ordered)

    if c in ("kraken_then_gm", "zenodo_then_gm", "second_then_best"):
        ordered = []
        if "kraken-htr" in all_tasks:
            ordered.append(("kraken-htr", all_tasks["kraken-htr"]))
        if "gm-htr" in all_tasks:
            ordered.append(("gm-htr", all_tasks["gm-htr"]))
        if not ordered:
            return HtrExecutionPlan(kind=HtrPlanKind.NONE)
        if len(ordered) == 1:
            k, fn = ordered[0]
            return HtrExecutionPlan(
                kind=HtrPlanKind.BEFORE_LLM_PARALLEL, tasks={k: fn}
            )
        return HtrExecutionPlan(kind=HtrPlanKind.BEFORE_LLM_ORDERED, ordered=ordered)

    # Unknown combination: behave like sequential (safe default)
    if not all_tasks:
        return HtrExecutionPlan(kind=HtrPlanKind.NONE)
    return HtrExecutionPlan(kind=HtrPlanKind.BEFORE_LLM_PARALLEL, tasks=dict(all_tasks))
