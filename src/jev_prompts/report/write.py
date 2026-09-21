# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開行から results/ へ markdown と図を書く。"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable
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

_MANAGED_FIGURE_PREFIXES = ("reliability-", "cost-accuracy-")


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
    dest.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".report-staging-", dir=dest))
    try:
        markdown, figures = _build_report(
            logs,
            staging,
            n_bootstrap=n_bootstrap,
            ci_level=ci_level,
            seed=seed,
        )
        installed_md, installed_figs = _install_report(dest, markdown, figures)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return WrittenReport(markdown=installed_md, figures=tuple(installed_figs))


def _build_report(
    logs: pl.DataFrame,
    staging: Path,
    *,
    n_bootstrap: int,
    ci_level: float,
    seed: int,
) -> tuple[Path, list[Path]]:
    figures_dir = staging / "figures"
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
        dest=staging,
    )
    reject_forbidden_text(text, source="report.md")
    markdown = staging / "report.md"
    markdown.write_text(text, encoding="utf-8")
    reject_forbidden_files((markdown, *figures))
    return markdown, figures


def _install_report(
    dest: Path, markdown: Path, figures: Iterable[Path]
) -> tuple[Path, list[Path]]:
    figures_dir = dest / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    installed = [_replace_file(src, figures_dir / src.name) for src in figures]
    published = _replace_file(markdown, dest / "report.md")
    keep = {path.name for path in installed}
    _clear_managed_figures(figures_dir, keep=keep)
    return published, installed


def _replace_file(src: Path, dest: Path) -> Path:
    part = dest.with_name(f".{dest.name}.part")
    shutil.copy2(src, part)
    part.replace(dest)
    return dest


def _clear_managed_figures(dest: Path, *, keep: set[str]) -> None:
    """今回書いていない管理対象図だけを消す。"""
    if not dest.is_dir():
        return
    for path in dest.iterdir():
        managed = path.name.startswith(_MANAGED_FIGURE_PREFIXES)
        if (
            path.is_file()
            and path.suffix == ".svg"
            and managed
            and path.name not in keep
        ):
            path.unlink()


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
