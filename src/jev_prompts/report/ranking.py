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
    """信号の高い順に残した prefix の正解率。coverage は 0.1 刻み。

    信号が無い行は最下位に置き、同点群をまたぐときは群内の期待値を使う。
    """
    prepared = prepare_cases(logs)
    if prepared.height == 0:
        return pl.DataFrame(schema=_schema())
    rows: list[dict[str, object]] = []
    for group in prepared.partition_by(list(GROUP_KEYS), maintain_order=True):
        rows.extend(_group_curve(group))
    if not rows:
        return pl.DataFrame(schema=_schema())
    return pl.DataFrame(rows).select(list(RISK_COVERAGE_COLUMNS))


def _group_curve(frame: pl.DataFrame) -> list[dict[str, object]]:
    groups = _signal_groups(frame)
    n = sum(len(group) for group in groups)
    if n == 0:
        return []
    keys = {name: frame[name][0] for name in GROUP_KEYS}
    rows: list[dict[str, object]] = []
    for coverage in COVERAGES:
        kept = max(1, min(n, round(coverage * n)))
        acc = _expected_prefix_accuracy(groups, kept)
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


def _signal_groups(frame: pl.DataFrame) -> list[list[bool]]:
    buckets: dict[float | None, list[bool]] = {}
    for sig, ok in zip(
        frame["threshold_signal"].to_list(),
        frame["correct"].to_list(),
        strict=True,
    ):
        key = None if sig is None else float(sig)
        buckets.setdefault(key, []).append(bool(ok))
    finite = sorted((k for k in buckets if k is not None), reverse=True)
    order: list[float | None] = [*finite]
    if None in buckets:
        order.append(None)
    return [buckets[key] for key in order]


def _expected_prefix_accuracy(groups: list[list[bool]], kept: int) -> float:
    remaining = kept
    hits = 0.0
    for outcomes in groups:
        if remaining <= 0:
            break
        size = len(outcomes)
        take = min(size, remaining)
        hits += take * (sum(outcomes) / size)
        remaining -= take
    return hits / kept


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
