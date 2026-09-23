# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""測定表の markdown。報告の本文は書かない。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from jev_prompts.prompts.catalog import CONDITIONS
from jev_prompts.report.a_errors import MODE_LABELS
from jev_prompts.report.intervals import PRIMARY_METRIC
from jev_prompts.report.prices import ModelPrice, render_price_table
from jev_prompts.report.tables import fmt_ci, fmt_float, fmt_int, markdown_table


def render_tables(
    *,
    metrics: pl.DataFrame,
    intervals: pl.DataFrame,
    calib: pl.DataFrame,
    figures: Sequence[Path],
    dest: Path,
    paired: pl.DataFrame,
    errors: pl.DataFrame,
    prices: tuple[ModelPrice, ...] | None,
    measured_on: date,
    note: str,
) -> str:
    """表と図へのリンクだけ。report.md の本文はここから出さない。"""
    parts = [
        "# 測定表",
        "",
        "ログから計算した表と図へのリンクである。",
        "報告の本文は report.md に、結果を見て書く。このファイルは報告ではない。",
        "",
        f"測定日: {measured_on.isoformat()}",
        "",
        "test 分割のみ。入力本文は置かない。",
        "",
    ]
    if note:
        parts.extend([note, ""])
    tasks = _ordered_values(metrics, "task")
    for task in tasks:
        parts.extend(
            _task_section(
                task=task,
                metrics=_task_frame(metrics, task),
                intervals=_task_frame(intervals, task),
                calib=_task_frame(calib, task),
                figures=figures,
                dest=dest,
            )
        )
    if not tasks:
        parts.extend(["測定値が無い。", ""])
    parts.extend(paired_section(paired))
    parts.extend(errors_section(errors))
    if prices:
        parts.extend(["### 測定単価", "", *render_price_table(prices), ""])
    return "\n".join(parts)


def _task_section(
    *,
    task: str,
    metrics: pl.DataFrame,
    intervals: pl.DataFrame,
    calib: pl.DataFrame,
    figures: Sequence[Path],
    dest: Path,
) -> list[str]:
    primary = PRIMARY_METRIC.get(task, "top1")
    reliability = _figure_link(
        figures, dest, f"reliability-{task}.svg", f"{task} reliability"
    )
    cost = _figure_link(
        figures, dest, f"cost-accuracy-{task}.svg", f"{task} cost accuracy"
    )
    return [
        f"### {task}",
        "",
        "#### 条件 × 指標",
        "",
        _matrix_table(task, metrics, intervals, primary),
        "",
        "#### 較正",
        "",
        _calibration_md(calib),
        "",
        reliability,
        "",
        "#### コスト × 精度",
        "",
        _cost_table(metrics, primary),
        "",
        cost,
        "",
    ]


def noul_hash_note(logs: pl.DataFrame) -> str:
    """同一本文の重複件数。解釈は書かない。"""
    if "content_hash" not in logs.columns or "task" not in logs.columns:
        return ""
    noul = logs.filter(pl.col("task") == "noul")
    if "condition" in noul.columns:
        noul = noul.filter(pl.col("condition") == "A")
    if noul.height == 0:
        return ""
    unique = noul["content_hash"].n_unique()
    if unique >= noul.height:
        return ""
    return (
        f"noul の test は {noul.height} 行中 content_hash が一意 {unique} 件。"
        "同一本文の重複を含む測定値をそのまま記録する。"
    )


def paired_section(paired: pl.DataFrame) -> list[str]:
    if paired.height == 0:
        return []
    return [
        "### 対応あり比較（A 対 他条件）",
        "",
        markdown_table(
            paired,
            [
                "task",
                "other",
                "metric",
                "difference",
                "ci_low",
                "ci_high",
                "p_holm",
            ],
            formatters={
                "difference": fmt_float,
                "ci_low": fmt_float,
                "ci_high": fmt_float,
                "p_holm": fmt_float,
            },
        ),
        "",
    ]


def errors_section(errors: pl.DataFrame) -> list[str]:
    lines = [
        "### A の誤答件数",
        "",
        "条件 A のうち、test で正解と一致しなかった件数を種類ごとに数えた表。",
        "入力の本文は載せていない。",
        "",
    ]
    if errors.height == 0:
        lines.extend(["A の誤答は無かった。", ""])
        return lines
    labeled = errors.with_columns(
        pl.col("mode").replace_strict(MODE_LABELS, default=pl.col("mode"))
    )
    lines.extend(
        [
            markdown_table(
                labeled,
                ["task", "mode", "n"],
                formatters={"n": _fmt_count},
            ),
            "",
        ]
    )
    return lines


def _fmt_count(value: object) -> str:
    if value is None:
        return ""
    return str(int(value))


def _matrix_table(
    task: str, metrics: pl.DataFrame, intervals: pl.DataFrame, primary: str
) -> str:
    frame = _attach_ci(metrics, intervals, primary, "primary_ci")
    columns = ["condition", "n", "n_primary", "error_rate", primary, "primary_ci"]
    labels = {"primary_ci": f"{primary} CI"}
    formatters: dict[str, object] = {
        "n": fmt_int,
        "n_primary": fmt_int,
        "error_rate": fmt_float,
        primary: fmt_float,
        "confident_error_rate": fmt_float,
        "ece": fmt_float,
        "tokens_per_1000": fmt_float,
        "latency_p50_ms": fmt_float,
        "latency_p95_ms": fmt_float,
    }
    if task == "score":
        frame = _attach_ci(frame, intervals, "spearman", "spearman_ci")
        columns.extend(["spearman", "spearman_ci"])
        labels["spearman_ci"] = "spearman CI"
        formatters["spearman"] = fmt_float
    columns.extend(
        [
            "confident_error_rate",
            "ece",
            "tokens_per_1000",
            "latency_p50_ms",
            "latency_p95_ms",
        ]
    )
    return markdown_table(
        _sort_conditions(frame),
        columns,
        labels=labels,
        formatters=formatters,
    )


def _attach_ci(
    metrics: pl.DataFrame, intervals: pl.DataFrame, metric: str, alias: str
) -> pl.DataFrame:
    empty = metrics.with_columns(pl.lit("").alias(alias))
    if intervals.height == 0:
        return empty
    subset = intervals.filter(pl.col("metric") == metric)
    if subset.height == 0:
        return empty
    renamed = subset.select(
        "task",
        "condition",
        "split",
        pl.col("ci_low").alias(f"{alias}_lo"),
        pl.col("ci_high").alias(f"{alias}_hi"),
    )
    joined = metrics.join(renamed, on=["task", "condition", "split"], how="left")
    cis = [
        fmt_ci(low, high)
        for low, high in zip(
            joined[f"{alias}_lo"].to_list(),
            joined[f"{alias}_hi"].to_list(),
            strict=True,
        )
    ]
    return joined.with_columns(pl.Series(alias, cis)).drop(f"{alias}_lo", f"{alias}_hi")


def _calibration_md(calib: pl.DataFrame) -> str:
    if calib.height == 0:
        return "較正に使える confidence が無い。"
    return markdown_table(
        _sort_conditions(calib),
        [
            "condition",
            "bin",
            "bin_low",
            "bin_high",
            "n",
            "mean_confidence",
            "accuracy",
            "ece",
        ],
        formatters={
            "bin": fmt_int,
            "bin_low": fmt_float,
            "bin_high": fmt_float,
            "n": fmt_int,
            "mean_confidence": fmt_float,
            "accuracy": fmt_float,
            "ece": fmt_float,
        },
    )


def _cost_table(metrics: pl.DataFrame, primary: str) -> str:
    columns = [
        "condition",
        "tokens_per_1000",
        primary,
        "latency_p50_ms",
        "latency_p95_ms",
    ]
    return markdown_table(
        _sort_conditions(metrics),
        columns,
        formatters={
            "tokens_per_1000": fmt_float,
            primary: fmt_float,
            "latency_p50_ms": fmt_float,
            "latency_p95_ms": fmt_float,
        },
    )


def _figure_link(figures: Sequence[Path], dest: Path, name: str, alt: str) -> str:
    for path in figures:
        if path.name == name:
            rel = path.resolve().relative_to(dest.resolve()).as_posix()
            return f"![{alt}]({rel})"
    return ""


def _task_frame(frame: pl.DataFrame, task: str) -> pl.DataFrame:
    if frame.height == 0 or "task" not in frame.columns:
        return frame
    return frame.filter(pl.col("task") == task)


def _ordered_values(frame: pl.DataFrame, column: str) -> list[str]:
    if frame.height == 0 or column not in frame.columns:
        return []
    seen: list[str] = []
    for value in frame[column].to_list():
        text = str(value)
        if text not in seen:
            seen.append(text)
    return seen


def _sort_conditions(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.height == 0 or "condition" not in frame.columns:
        return frame
    order = {name: index for index, name in enumerate(CONDITIONS)}
    return (
        frame.with_columns(
            pl.col("condition")
            .replace_strict(order, default=len(CONDITIONS), return_dtype=pl.Int64)
            .alias("_ord")
        )
        .sort("_ord", "condition")
        .drop("_ord")
    )
