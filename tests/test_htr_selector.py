"""HTR combination selector (Glyph Machina, Zenodo kraken-htr, shell / LLM-only)."""

from __future__ import annotations

import pytest

from transcriber_shell.config import Settings
from transcriber_shell.htr.base import HtrResult
from transcriber_shell.htr.parallel import run_htr_ordered
from transcriber_shell.htr.selector import HtrPlanKind, plan_htr_execution


def test_plan_shell_skips_htr_even_when_tasks_exist() -> None:
    s = Settings(htr_combination="shell")
    tasks = {
        "gm-htr": lambda: HtrResult(text="x", backend="gm-htr", line_count=1),
        "kraken-htr": lambda: HtrResult(text="y", backend="kraken-htr", line_count=1),
    }
    plan = plan_htr_execution(s, tasks)
    assert plan.kind == HtrPlanKind.NONE


def test_plan_gm_then_kraken_order() -> None:
    order: list[str] = []

    def gm() -> HtrResult:
        order.append("gm")
        return HtrResult(text="a", backend="gm-htr", line_count=1)

    def kr() -> HtrResult:
        order.append("kr")
        return HtrResult(text="b", backend="kraken-htr", line_count=1)

    tasks = {"gm-htr": gm, "kraken-htr": kr}
    s = Settings(htr_combination="gm_then_kraken", htr_parallel=True)
    plan = plan_htr_execution(s, tasks)
    assert plan.kind == HtrPlanKind.BEFORE_LLM_ORDERED
    assert plan.ordered is not None
    run_htr_ordered(plan.ordered)
    assert order == ["gm", "kr"]


def test_plan_kraken_then_gm_order() -> None:
    order: list[str] = []

    def gm() -> HtrResult:
        order.append("gm")
        return HtrResult(text="a", backend="gm-htr", line_count=1)

    def kr() -> HtrResult:
        order.append("kr")
        return HtrResult(text="b", backend="kraken-htr", line_count=1)

    tasks = {"gm-htr": gm, "kraken-htr": kr}
    s = Settings(htr_combination="kraken_then_gm")
    plan = plan_htr_execution(s, tasks)
    assert plan.kind == HtrPlanKind.BEFORE_LLM_ORDERED
    run_htr_ordered(plan.ordered or [])
    assert order == ["kr", "gm"]


def test_plan_default_parallel_when_htr_parallel_true() -> None:
    tasks = {"kraken-htr": lambda: HtrResult(text="z", backend="kraken-htr", line_count=1)}
    s = Settings(htr_combination="default", htr_parallel=True)
    plan = plan_htr_execution(s, tasks)
    assert plan.kind == HtrPlanKind.WITH_LLM_PARALLEL
    assert plan.tasks == tasks


def test_plan_default_sequential_when_htr_parallel_false() -> None:
    tasks = {"kraken-htr": lambda: HtrResult(text="z", backend="kraken-htr", line_count=1)}
    s = Settings(htr_combination="default", htr_parallel=False)
    plan = plan_htr_execution(s, tasks)
    assert plan.kind == HtrPlanKind.BEFORE_LLM_PARALLEL


def test_plan_zenodo_alias_filters_to_kraken_only() -> None:
    s = Settings(htr_combination="zenodo")
    tasks = {
        "gm-htr": lambda: HtrResult(text="g", backend="gm-htr", line_count=1),
        "kraken-htr": lambda: HtrResult(text="k", backend="kraken-htr", line_count=1),
    }
    plan = plan_htr_execution(s, tasks)
    assert plan.kind == HtrPlanKind.BEFORE_LLM_PARALLEL
    assert plan.tasks is not None and set(plan.tasks) == {"kraken-htr"}


def test_settings_htr_combination_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="htr_combination"):
        Settings(htr_combination="not-a-mode")
