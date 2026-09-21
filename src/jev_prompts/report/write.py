# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開行から results/ へ markdown と図を書く。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from jev_prompts.config import BOOTSTRAP_REPLICATES, CI_LEVEL, STATS_SEED
from jev_prompts.data.schema import BODY_COLUMNS
from jev_prompts.metrics import aggregate_metrics
from jev_prompts.report.calibration import calibration_table
from jev_prompts.report.forbidden import reject_forbidden_files, reject_forbidden_text
from jev_prompts.report.intervals import metric_intervals
from jev_prompts.report.plots import write_task_figures
from jev_prompts.report.render import render_report
from jev_prompts.runners.fanout import drop_fanout_rows
from jev_prompts.runners.schema import REQUEST_LOG_COLUMNS, to_published


@dataclass(frozen=True, slots=True)
class WrittenReport:
    markdown: Path
    figures: tuple[Path, ...]


def write_report(
    logs: pl.DataFrame,
    dest: Path,
    *,
    n_bootstrap: int = BOOTSTRAP_REPLICATES,
    ci_level: float = CI_LEVEL,
    seed: int = STATS_SEED,
) -> WrittenReport:
    """指標マトリクス・較正・コスト×精度を markdown と図に書く。"""
    dest = dest.resolve()
    figures_dir = dest / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    frame = _public_logs(logs)
    metrics = aggregate_metrics(frame)
    intervals = metric_intervals(
        frame, n_bootstrap=n_bootstrap, ci_level=ci_level, seed=seed
    )
    calib = calibration_table(frame)
    figures = _write_figures(metrics, calib, figures_dir)
    text = render_report(
        metrics=metrics,
        intervals=intervals,
        calib=calib,
        figures=figures,
        dest=dest,
    )
    reject_forbidden_text(text, source="report.md")
    markdown = dest / "report.md"
    markdown.write_text(text, encoding="utf-8")
    reject_forbidden_files((markdown, *figures))
    return WrittenReport(markdown=markdown, figures=tuple(figures))


def _public_logs(logs: pl.DataFrame) -> pl.DataFrame:
    frame = drop_fanout_rows(logs)
    if set(REQUEST_LOG_COLUMNS) <= set(frame.columns):
        frame = to_published(frame)
    body = [name for name in frame.columns if name in BODY_COLUMNS]
    if body:
        frame = frame.drop(body)
    if "split" in frame.columns and "test" in set(frame["split"].to_list()):
        return frame.filter(pl.col("split") == "test")
    return frame


def _write_figures(
    metrics: pl.DataFrame, calib: pl.DataFrame, dest: Path
) -> list[Path]:
    paths: list[Path] = []
    if metrics.height == 0:
        return paths
    tasks = list(dict.fromkeys(metrics["task"].to_list()))
    for task in tasks:
        paths.extend(
            write_task_figures(
                task=str(task),
                metrics=metrics.filter(pl.col("task") == task),
                calib=calib.filter(pl.col("task") == task) if calib.height else calib,
                dest=dest,
            )
        )
    return paths
