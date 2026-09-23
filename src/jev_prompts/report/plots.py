# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""reliability diagram、risk-coverage、コスト×精度の散布図。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from jev_prompts.prompts.catalog import CONDITIONS
from jev_prompts.report.intervals import PRIMARY_METRIC


def write_task_figures(
    *,
    task: str,
    metrics: pl.DataFrame,
    calib: pl.DataFrame,
    ranking: pl.DataFrame,
    dest: Path,
) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    reliability = dest / f"reliability-{task}.svg"
    coverage = dest / f"risk-coverage-{task}.svg"
    cost = dest / f"cost-accuracy-{task}.svg"
    _reliability_diagram(calib, reliability)
    _risk_coverage(ranking, coverage)
    _cost_accuracy(metrics, task, cost)
    return [reliability, coverage, cost]


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _reliability_diagram(calib: pl.DataFrame, path: Path) -> None:
    plt = _pyplot()
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", color="0.5")
    for condition in _conditions(calib):
        part = calib.filter((pl.col("condition") == condition) & (pl.col("n") > 0))
        if part.height == 0:
            continue
        ax.plot(
            part["mean_probability"].to_list(),
            part["accuracy"].to_list(),
            marker="o",
            label=condition,
        )
    ax.set_xlabel("probability")
    ax.set_ylabel("accuracy")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    if _conditions(calib):
        ax.legend()
    _save(fig, plt, path)


def _risk_coverage(ranking: pl.DataFrame, path: Path) -> None:
    plt = _pyplot()
    fig, ax = plt.subplots()
    for condition in _conditions(ranking):
        part = ranking.filter(pl.col("condition") == condition)
        if part.height == 0:
            continue
        ax.plot(
            part["coverage"].to_list(),
            part["accuracy"].to_list(),
            marker="o",
            label=condition,
        )
    ax.set_xlabel("coverage")
    ax.set_ylabel("accuracy")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    if _conditions(ranking):
        ax.legend()
    _save(fig, plt, path)


def _cost_accuracy(metrics: pl.DataFrame, task: str, path: Path) -> None:
    plt = _pyplot()
    fig, ax = plt.subplots()
    primary = PRIMARY_METRIC.get(task, "top1")
    for condition in _conditions(metrics):
        part = metrics.filter(pl.col("condition") == condition)
        if part.height == 0:
            continue
        xs = part["tokens_per_1000"].to_list()
        ys = part[primary].to_list()
        ax.scatter(xs, ys)
        if xs and ys and xs[0] is not None and ys[0] is not None:
            ax.annotate(condition, (float(xs[0]), float(ys[0])))
    ax.set_xlabel("tokens_per_1000")
    ax.set_ylabel(primary)
    _save(fig, plt, path)


def _conditions(frame: pl.DataFrame) -> list[str]:
    if frame.height == 0 or "condition" not in frame.columns:
        return []
    present = set(frame["condition"].to_list())
    known = [name for name in CONDITIONS if name in present]
    extra = sorted(name for name in present if name not in set(CONDITIONS))
    return known + extra


def _save(fig, plt, path: Path) -> None:
    fig.savefig(path, format="svg", bbox_inches="tight")
    plt.close(fig)
