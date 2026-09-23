# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開行から測定表と図を書く。report.md は書かない。"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from jev_prompts.config import BOOTSTRAP_REPLICATES, CI_LEVEL, STATS_SEED
from jev_prompts.data.schema import BODY_COLUMNS
from jev_prompts.metrics import aggregate_metrics
from jev_prompts.report.a_errors import classify_a_errors
from jev_prompts.report.calibration import calibration_table
from jev_prompts.report.forbidden import reject_forbidden_files, reject_forbidden_text
from jev_prompts.report.intervals import metric_intervals
from jev_prompts.report.plots import write_task_figures
from jev_prompts.report.prices import ModelPrice
from jev_prompts.report.render import noul_hash_note, render_tables
from jev_prompts.runners.fanout import drop_fanout_rows
from jev_prompts.runners.schema import REQUEST_LOG_COLUMNS, to_published
from jev_prompts.stats.compare import compare_paired

_MANAGED_FIGURE_PREFIXES = ("reliability-", "cost-accuracy-")


@dataclass(frozen=True, slots=True)
class WrittenReport:
    markdown: Path
    figures: tuple[Path, ...]


def eval_logs(logs: pl.DataFrame) -> pl.DataFrame:
    """報告に使う行は test。fan-out 行は混ぜない。"""
    frame = drop_fanout_rows(logs)
    if "split" in frame.columns:
        return frame.filter(pl.col("split") == "test")
    return frame


def write_report(
    logs: pl.DataFrame,
    dest: Path,
    *,
    n_bootstrap: int = BOOTSTRAP_REPLICATES,
    ci_level: float = CI_LEVEL,
    seed: int = STATS_SEED,
    prices: tuple[ModelPrice, ...] | None = None,
    measured_on: date | None = None,
    errors: pl.DataFrame | None = None,
) -> WrittenReport:
    """測定表（tables.md）と図を書く。report.md は触らない。"""
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
            prices=prices,
            measured_on=measured_on or date.today(),
            errors=errors,
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
    prices: tuple[ModelPrice, ...] | None,
    measured_on: date,
    errors: pl.DataFrame | None,
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
    counted = errors if errors is not None else classify_a_errors(frame)
    paired = (
        compare_paired(frame, n_bootstrap=n_bootstrap, ci_level=ci_level, seed=seed)
        if frame.height
        else pl.DataFrame()
    )
    text = render_tables(
        metrics=metrics,
        intervals=intervals,
        calib=calib,
        figures=figures,
        dest=staging,
        paired=paired,
        errors=counted,
        prices=prices,
        measured_on=measured_on,
        note=noul_hash_note(frame),
    )
    reject_forbidden_text(text, source="tables.md")
    markdown = staging / "tables.md"
    markdown.write_text(text, encoding="utf-8")
    reject_forbidden_files((markdown, *figures))
    return markdown, figures


def _install_report(
    dest: Path, markdown: Path, figures: Iterable[Path]
) -> tuple[Path, list[Path]]:
    figures_dir = dest / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    installed = [_replace_file(src, figures_dir / src.name) for src in figures]
    published = _replace_file(markdown, dest / "tables.md")
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
