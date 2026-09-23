# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""閾値の信号で確信度の高い順に残したときの正解率。"""

from __future__ import annotations

from typing import Final

import polars as pl

from jev_prompts.metrics import GROUP_KEYS, prepare_cases

COVERAGES: Final[tuple[float, ...]] = tuple(i / 10.0 for i in range(1, 11))
RISK_COVERAGE_COLUMNS: Final[tuple[str, ...]] = (
    *GROUP_KEYS,
    "coverage",
    "n_kept",
    "accuracy",
    "risk",
)


def risk_coverage_table(logs: pl.DataFrame) -> pl.DataFrame:
    """信号の高い順に残した prefix の正解率。coverage は 0.1 刻み。"""
    prepared = prepare_cases(logs)
    scored = prepared.filter(pl.col("threshold_signal").is_not_null())
    if scored.height == 0:
        return pl.DataFrame(schema=_schema())
    rows: list[dict[str, object]] = []
    for group in scored.partition_by(list(GROUP_KEYS), maintain_order=True):
        rows.extend(_group_curve(group))
    if not rows:
        return pl.DataFrame(schema=_schema())
    return pl.DataFrame(rows).select(list(RISK_COVERAGE_COLUMNS))


def _group_curve(frame: pl.DataFrame) -> list[dict[str, object]]:
    has_id = "case_id" in frame.columns
    if has_id:
        ordered = frame.sort(["threshold_signal", "case_id"], descending=[True, False])
    else:
        ordered = frame.sort("threshold_signal", descending=True)
    correct = [bool(v) for v in ordered["correct"].to_list()]
    n = len(correct)
    if n == 0:
        return []
    keys = {name: ordered[name][0] for name in GROUP_KEYS}
    hits = 0
    prefix_acc = [0.0] * n
    for index, ok in enumerate(correct):
        if ok:
            hits += 1
        prefix_acc[index] = hits / (index + 1)
    rows: list[dict[str, object]] = []
    for coverage in COVERAGES:
        kept = max(1, min(n, round(coverage * n)))
        acc = prefix_acc[kept - 1]
        rows.append(
            {
                **keys,
                "coverage": coverage,
                "n_kept": kept,
                "accuracy": acc,
                "risk": 1.0 - acc,
            }
        )
    return rows


def _schema() -> dict[str, pl.DataType]:
    return {
        "task": pl.String,
        "condition": pl.String,
        "split": pl.String,
        "coverage": pl.Float64,
        "n_kept": pl.UInt32,
        "accuracy": pl.Float64,
        "risk": pl.Float64,
    }
