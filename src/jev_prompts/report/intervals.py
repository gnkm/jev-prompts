# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""条件ごとの指標にブートストラップ区間を付ける。"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Final

import polars as pl

from jev_prompts.config import CI_LEVEL, STATS_SEED
from jev_prompts.metrics import GROUP_KEYS, prepare_cases
from jev_prompts.report.errors import ReportError
from jev_prompts.stats.bootstrap import percentile_ci
from jev_prompts.stats.summaries import mean_abs_error, mean_binary, pairwise_auc

INTERVAL_COLUMNS: Final[tuple[str, ...]] = (
    *GROUP_KEYS,
    "metric",
    "value",
    "ci_low",
    "ci_high",
    "n",
    "n_bootstrap",
    "ci_level",
)

PRIMARY_METRIC: Final[dict[str, str]] = {
    "choice": "top1",
    "score": "mae",
    "noul": "auc",
}

Stat = Callable[[Sequence[object]], float | None]


def metric_intervals(
    logs: pl.DataFrame,
    *,
    n_bootstrap: int,
    ci_level: float = CI_LEVEL,
    seed: int = STATS_SEED,
) -> pl.DataFrame:
    """task / condition / split ごとに主指標と confident 誤答率の区間を出す。"""
    _require_interval_args(n_bootstrap, ci_level)
    prepared = prepare_cases(logs)
    if prepared.height == 0:
        return pl.DataFrame(schema=_schema())
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for group in prepared.partition_by(list(GROUP_KEYS), maintain_order=True):
        rows.extend(_group_intervals(group, n_bootstrap, ci_level, rng))
    if not rows:
        return pl.DataFrame(schema=_schema())
    return pl.DataFrame(rows).select(list(INTERVAL_COLUMNS))


def _require_interval_args(n_bootstrap: int, ci_level: float) -> None:
    if not isinstance(n_bootstrap, int) or n_bootstrap <= 0:
        raise ReportError("n_bootstrap は正の整数である")
    if not 0.0 < ci_level < 1.0:
        raise ReportError("ci_level は 0 より大きく 1 より小さい")


def _group_intervals(
    frame: pl.DataFrame,
    n_bootstrap: int,
    ci_level: float,
    rng: random.Random,
) -> list[dict[str, object]]:
    keys = {name: frame[name][0] for name in GROUP_KEYS}
    rows: list[dict[str, object]] = []
    for metric, values, stat in _targets(frame):
        observed = stat(values)
        if observed is None:
            continue
        samples = _resample(values, stat, n_bootstrap, rng)
        low, high = _ci(samples, ci_level)
        rows.append(
            {
                **keys,
                "metric": metric,
                "value": observed,
                "ci_low": low,
                "ci_high": high,
                "n": len(values),
                "n_bootstrap": len(samples),
                "ci_level": ci_level,
            }
        )
    return rows


def _targets(frame: pl.DataFrame) -> list[tuple[str, list[object], Stat]]:
    task = str(frame["task"][0])
    out: list[tuple[str, list[object], Stat]] = []
    primary = _primary_target(frame, task)
    if primary is not None:
        out.append(primary)
    out.append(
        ("confident_error_rate", frame["confident_error"].to_list(), mean_binary)
    )
    return out


def _primary_target(
    frame: pl.DataFrame, task: str
) -> tuple[str, list[object], Stat] | None:
    if task == "choice":
        return ("top1", frame["correct"].to_list(), mean_binary)
    valid = frame.filter(pl.col("primary_valid"))
    if task == "score":
        pairs = list(
            zip(valid["pred"].to_list(), valid["gold_score"].to_list(), strict=True)
        )
        return ("mae", pairs, mean_abs_error)
    if task == "noul":
        pairs = list(
            zip(valid["pred"].to_list(), valid["gold_yes"].to_list(), strict=True)
        )
        return ("auc", pairs, pairwise_auc)
    return None


def _resample(
    values: Sequence[object],
    stat: Stat,
    n_bootstrap: int,
    rng: random.Random,
) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    samples: list[float] = []
    for _ in range(n_bootstrap):
        drawn = [values[rng.randrange(n)] for _ in range(n)]
        value = stat(drawn)
        if value is not None:
            samples.append(value)
    return samples


def _ci(samples: Sequence[float], ci_level: float) -> tuple[float | None, float | None]:
    if len(samples) < 2:
        return (None, None)
    return percentile_ci(samples, ci_level)


def _schema() -> dict[str, pl.DataType]:
    return {
        "task": pl.String,
        "condition": pl.String,
        "split": pl.String,
        "metric": pl.String,
        "value": pl.Float64,
        "ci_low": pl.Float64,
        "ci_high": pl.Float64,
        "n": pl.Int64,
        "n_bootstrap": pl.Int64,
        "ci_level": pl.Float64,
    }
