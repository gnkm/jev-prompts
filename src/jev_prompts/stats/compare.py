# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""同じケース集合で A 対各条件を比べ、差・区間・Holm を出す。"""

from __future__ import annotations

import random
from typing import Final

import polars as pl

from jev_prompts.config.stats import (
    BASELINE_CONDITION,
    BOOTSTRAP_REPLICATES,
    CI_LEVEL,
    STATS_SEED,
)
from jev_prompts.metrics.aggregate import MetricsError, prepare_cases
from jev_prompts.prompts.catalog import CONDITIONS
from jev_prompts.stats.bootstrap import (
    bootstrap_two_sided_p,
    paired_bootstrap_diffs,
    percentile_ci,
)
from jev_prompts.stats.holm import holm_adjust
from jev_prompts.stats.mcnemar import mcnemar_p_value
from jev_prompts.stats.summaries import (
    expected_calibration_error,
    mean_abs_error,
    mean_binary,
    mean_optional,
    pairwise_auc,
)

COMPARE_COLUMNS: Final[tuple[str, ...]] = (
    "task",
    "split",
    "baseline",
    "other",
    "metric",
    "n_paired",
    "value_baseline",
    "value_other",
    "difference",
    "ci_low",
    "ci_high",
    "ci_level",
    "p_raw",
    "p_holm",
    "method",
    "n_discordant",
    "n_baseline_only",
    "n_other_only",
    "n_bootstrap",
)

_METHOD_MCNEMAR: Final = "mcnemar+bootstrap"
_METHOD_BOOTSTRAP: Final = "bootstrap"


class StatsError(ValueError):
    """対応づけできない、または検定の入力が足りない。"""


def compare_paired(
    logs: pl.DataFrame,
    *,
    baseline: str = BASELINE_CONDITION,
    n_bootstrap: int = BOOTSTRAP_REPLICATES,
    ci_level: float = CI_LEVEL,
    seed: int = STATS_SEED,
) -> pl.DataFrame:
    """同一 case_id で baseline 対その他を比べる。p 値だけでは返さない。"""
    _require_interval_args(n_bootstrap, ci_level)
    prepared = _prepare_or_raise(logs)
    if prepared.height == 0:
        return _empty()
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    for task, split in _task_splits(prepared):
        rows.extend(
            _rows_for_split(
                prepared,
                task=task,
                split=split,
                baseline=baseline,
                n_bootstrap=n_bootstrap,
                ci_level=ci_level,
                rng=rng,
            )
        )
    if not rows:
        return _empty()
    return _attach_holm(pl.DataFrame(rows)).select(list(COMPARE_COLUMNS))


def _require_interval_args(n_bootstrap: int, ci_level: float) -> None:
    if not isinstance(n_bootstrap, int) or n_bootstrap <= 0:
        raise StatsError("n_bootstrap は正の整数である")
    if not 0.0 < ci_level < 1.0:
        raise StatsError("ci_level は 0 より大きく 1 より小さい")


def _prepare_or_raise(logs: pl.DataFrame) -> pl.DataFrame:
    if "case_id" not in logs.columns:
        raise StatsError("対応あり検定に case_id が無い")
    try:
        prepared = prepare_cases(logs)
    except MetricsError as exc:
        raise StatsError(str(exc)) from exc
    _reject_duplicate_cases(prepared)
    return prepared


def _reject_duplicate_cases(prepared: pl.DataFrame) -> None:
    keys = ["task", "condition", "split", "case_id"]
    dup = prepared.group_by(keys).len().filter(pl.col("len") > 1)
    if dup.height > 0:
        raise StatsError("同一条件に case_id が重複している")


def _task_splits(prepared: pl.DataFrame) -> list[tuple[str, str]]:
    pairs = prepared.select("task", "split").unique(maintain_order=True)
    return [(row["task"], row["split"]) for row in pairs.iter_rows(named=True)]


def _rows_for_split(
    prepared: pl.DataFrame,
    *,
    task: str,
    split: str,
    baseline: str,
    n_bootstrap: int,
    ci_level: float,
    rng: random.Random,
) -> list[dict[str, object]]:
    subset = prepared.filter((pl.col("task") == task) & (pl.col("split") == split))
    others = _other_conditions(subset, baseline)
    rows: list[dict[str, object]] = []
    for other in others:
        paired = _pair_conditions(subset, baseline, other)
        if paired is None:
            continue
        rows.extend(
            _rows_for_pair(
                paired,
                task=task,
                split=split,
                baseline=baseline,
                other=other,
                n_bootstrap=n_bootstrap,
                ci_level=ci_level,
                rng=rng,
                metrics=_metric_kinds(task),
            )
        )
    for other in others:
        paired = _pair_conditions(subset, baseline, other)
        if paired is None:
            continue
        rows.extend(
            _rows_for_pair(
                paired,
                task=task,
                split=split,
                baseline=baseline,
                other=other,
                n_bootstrap=n_bootstrap,
                ci_level=ci_level,
                rng=rng,
                metrics=(("ece", "bootstrap"),),
            )
        )
    return rows


def _other_conditions(subset: pl.DataFrame, baseline: str) -> list[str]:
    present = set(subset["condition"].to_list())
    known = [name for name in CONDITIONS if name != baseline and name in present]
    extra = sorted(name for name in present if name != baseline and name not in known)
    return known + extra


def _pair_conditions(
    subset: pl.DataFrame, baseline: str, other: str
) -> pl.DataFrame | None:
    keep = (
        "case_id",
        "correct",
        "pred",
        "gold_score",
        "gold_yes",
        "threshold_signal",
        "cal_probability",
        "primary_valid",
    )
    left = subset.filter(pl.col("condition") == baseline).select(list(keep))
    right = subset.filter(pl.col("condition") == other).select(list(keep))
    if left.height == 0 or right.height == 0:
        return None
    joined = left.join(right, on="case_id", suffix="_other")
    if joined.height == 0:
        return None
    return joined


def _rows_for_pair(
    paired: pl.DataFrame,
    *,
    task: str,
    split: str,
    baseline: str,
    other: str,
    n_bootstrap: int,
    ci_level: float,
    rng: random.Random,
    metrics: tuple[tuple[str, str], ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for metric, kind in metrics:
        row = _one_metric(
            paired,
            metric=metric,
            kind=kind,
            n_bootstrap=n_bootstrap,
            ci_level=ci_level,
            rng=rng,
        )
        if row is None:
            continue
        row.update(
            task=task,
            split=split,
            baseline=baseline,
            other=other,
        )
        rows.append(row)
    return rows


def _metric_kinds(task: str) -> tuple[tuple[str, str], ...]:
    if task == "choice":
        return (
            ("accuracy", "mcnemar"),
            ("confidence", "bootstrap"),
        )
    if task == "score":
        return (
            ("mae", "bootstrap"),
            ("confidence", "bootstrap"),
        )
    if task == "noul":
        return (
            ("accuracy", "mcnemar"),
            ("auc", "bootstrap"),
            ("confidence", "bootstrap"),
        )
    return ()


def _one_metric(
    paired: pl.DataFrame,
    *,
    metric: str,
    kind: str,
    n_bootstrap: int,
    ci_level: float,
    rng: random.Random,
) -> dict[str, object] | None:
    left, right = _series_for_metric(paired, metric)
    if not left:
        return None
    observed_a = _stat_for(metric)(left)
    observed_b = _stat_for(metric)(right)
    if observed_a is None or observed_b is None:
        return None
    diffs = paired_bootstrap_diffs(
        left, right, _stat_for(metric), n_bootstrap=n_bootstrap, rng=rng
    )
    if not diffs:
        return None
    ci_low, ci_high = percentile_ci(diffs, ci_level)
    p_raw = _p_for(kind, paired, metric, diffs)
    if metric == "accuracy":
        n_base, n_oth, n_disc = _mcnemar_cells(paired)
    else:
        n_base, n_oth, n_disc = None, None, None
    return {
        "metric": metric,
        "n_paired": len(left),
        "value_baseline": observed_a,
        "value_other": observed_b,
        "difference": observed_a - observed_b,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_level": ci_level,
        "p_raw": p_raw,
        "p_holm": None,
        "method": _METHOD_MCNEMAR if kind == "mcnemar" else _METHOD_BOOTSTRAP,
        "n_discordant": n_disc,
        "n_baseline_only": n_base,
        "n_other_only": n_oth,
        "n_bootstrap": len(diffs),
    }


def _p_for(kind: str, paired: pl.DataFrame, metric: str, diffs: list[float]) -> float:
    if kind == "mcnemar" and metric == "accuracy":
        n_base, n_oth, _n_disc = _mcnemar_cells(paired)
        return mcnemar_p_value(n_base, n_oth)
    return bootstrap_two_sided_p(diffs)


def _mcnemar_cells(paired: pl.DataFrame) -> tuple[int, int, int]:
    a = paired["correct"].to_list()
    b = paired["correct_other"].to_list()
    n_base = sum(1 for x, y in zip(a, b, strict=True) if bool(x) and not bool(y))
    n_oth = sum(1 for x, y in zip(a, b, strict=True) if (not bool(x)) and bool(y))
    return n_base, n_oth, n_base + n_oth


def _stat_for(metric: str):
    if metric == "accuracy":
        return mean_binary
    if metric == "mae":
        return mean_abs_error
    if metric == "auc":
        return pairwise_auc
    if metric == "ece":
        return expected_calibration_error
    return mean_optional


def _series_for_metric(
    paired: pl.DataFrame, metric: str
) -> tuple[list[object], list[object]]:
    if metric == "accuracy":
        return (paired["correct"].to_list(), paired["correct_other"].to_list())
    if metric == "mae":
        return _mae_pairs(paired)
    if metric == "auc":
        return _auc_pairs(paired)
    if metric == "ece":
        return _ece_pairs(paired)
    return _confidence_pairs(paired)


def _mae_pairs(paired: pl.DataFrame) -> tuple[list[object], list[object]]:
    rows = paired.filter(
        pl.col("primary_valid")
        & pl.col("primary_valid_other")
        & pl.col("pred").is_not_null()
        & pl.col("pred_other").is_not_null()
        & pl.col("gold_score").is_not_null()
    )
    left = list(zip(rows["pred"].to_list(), rows["gold_score"].to_list(), strict=True))
    gold = rows["gold_score"].to_list()
    right = list(zip(rows["pred_other"].to_list(), gold, strict=True))
    return left, right


def _auc_pairs(paired: pl.DataFrame) -> tuple[list[object], list[object]]:
    rows = paired.filter(
        pl.col("primary_valid")
        & pl.col("primary_valid_other")
        & pl.col("pred").is_not_null()
        & pl.col("pred_other").is_not_null()
        & pl.col("gold_yes").is_not_null()
    )
    gold = rows["gold_yes"].to_list()
    left = list(zip(rows["pred"].to_list(), gold, strict=True))
    right = list(zip(rows["pred_other"].to_list(), gold, strict=True))
    return left, right


def _confidence_pairs(paired: pl.DataFrame) -> tuple[list[object], list[object]]:
    rows = paired.filter(
        pl.col("threshold_signal").is_not_null()
        & pl.col("threshold_signal_other").is_not_null()
    )
    return rows["threshold_signal"].to_list(), rows["threshold_signal_other"].to_list()


def _ece_pairs(paired: pl.DataFrame) -> tuple[list[object], list[object]]:
    rows = paired.filter(
        pl.col("cal_probability").is_not_null()
        & pl.col("cal_probability_other").is_not_null()
    )
    gold = rows["correct"].to_list()
    gold_other = rows["correct_other"].to_list()
    left = list(zip(rows["cal_probability"].to_list(), gold, strict=True))
    right = list(zip(rows["cal_probability_other"].to_list(), gold_other, strict=True))
    return left, right


def _attach_holm(frame: pl.DataFrame) -> pl.DataFrame:
    blocks: list[pl.DataFrame] = []
    for group in frame.partition_by(["task", "split", "metric"], maintain_order=True):
        adj = holm_adjust([float(v) for v in group["p_raw"].to_list()])
        blocks.append(group.with_columns(pl.Series("p_holm", adj)))
    return pl.concat(blocks)


def _empty() -> pl.DataFrame:
    return pl.DataFrame(schema=_result_schema())


def _result_schema() -> dict[str, pl.DataType]:
    return {
        "task": pl.String,
        "split": pl.String,
        "baseline": pl.String,
        "other": pl.String,
        "metric": pl.String,
        "n_paired": pl.Int64,
        "value_baseline": pl.Float64,
        "value_other": pl.Float64,
        "difference": pl.Float64,
        "ci_low": pl.Float64,
        "ci_high": pl.Float64,
        "ci_level": pl.Float64,
        "p_raw": pl.Float64,
        "p_holm": pl.Float64,
        "method": pl.String,
        "n_discordant": pl.Int64,
        "n_baseline_only": pl.Int64,
        "n_other_only": pl.Int64,
        "n_bootstrap": pl.Int64,
    }
