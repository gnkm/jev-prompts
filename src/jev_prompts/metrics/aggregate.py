# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""RequestLog を Polars で集計する。合格ラインは計算しない。"""

from __future__ import annotations

from typing import Final

import polars as pl

from jev_prompts.config.metrics import (
    CONFIDENT_THRESHOLD,
    ECE_BINS,
    LATENCY_P50,
    LATENCY_P95,
    NOUL_DECISION_THRESHOLD,
    TOKENS_PER_THOUSAND,
)
from jev_prompts.data.schema import NOUL_GOLD, SCORE_GOLD

GROUP_KEYS: Final[tuple[str, ...]] = ("task", "condition", "split")

METRIC_COLUMNS: Final[tuple[str, ...]] = (
    *GROUP_KEYS,
    "n",
    "n_error",
    "n_primary",
    "error_rate",
    "top1",
    "mae",
    "spearman",
    "auc",
    "confident_error_rate",
    "ece",
    "tokens_per_1000",
    "latency_p50_ms",
    "latency_p95_ms",
)

_REQUIRED: Final[tuple[str, ...]] = ("task", "condition", "split", "answer", "gold")
_OPTIONAL: Final[tuple[str, ...]] = (
    "confidence",
    "usage_tokens",
    "latency_ms",
    "error",
)

_SCORE_GOLD_STR: Final[dict[str, str]] = {
    **{label: str(value) for label, value in SCORE_GOLD.items()},
    **{str(value): str(value) for value in SCORE_GOLD.values()},
}
_NOUL_GOLD_STR: Final[dict[str, str]] = {
    **{str(src): str(dst) for src, dst in NOUL_GOLD.items()},
    "yes": "yes",
    "no": "no",
}
_YES_LABELS: Final[tuple[str, ...]] = ("yes",)
_QUANTILE_INTERPOLATION: Final = "linear"


class MetricsError(ValueError):
    """ログ列が足りない、または集計できない。"""


def aggregate_metrics(logs: pl.DataFrame) -> pl.DataFrame:
    """課題タイプ別の主指標と共通 4 指標を task / condition / split ごとに出す。

    合格ライン（A 対 B1 の差など）は列にもアサーションにもしない。
    """
    prepared = prepare_cases(logs)
    if prepared.height == 0:
        return pl.DataFrame(schema=_result_schema())

    grouped = prepared.group_by(list(GROUP_KEYS), maintain_order=True).agg(
        n=pl.len(),
        n_error=pl.col("has_error").sum(),
        n_primary=pl.col("primary_valid").sum(),
        error_rate=pl.col("has_error").mean(),
        top1=_top1_expr(),
        mae=_mae_expr(),
        spearman=_spearman_expr(),
        confident_error_rate=pl.col("confident_error").mean(),
        tokens_per_1000=(pl.col("usage_tokens").mean() * TOKENS_PER_THOUSAND),
        latency_p50_ms=pl.col("latency_ms").quantile(
            LATENCY_P50, interpolation=_QUANTILE_INTERPOLATION
        ),
        latency_p95_ms=pl.col("latency_ms").quantile(
            LATENCY_P95, interpolation=_QUANTILE_INTERPOLATION
        ),
    )
    return (
        grouped.join(_auc_by_group(prepared), on=list(GROUP_KEYS), how="left")
        .join(_ece_by_group(prepared), on=list(GROUP_KEYS), how="left")
        .select(list(METRIC_COLUMNS))
    )


def _result_schema() -> dict[str, pl.DataType]:
    return {
        "task": pl.String,
        "condition": pl.String,
        "split": pl.String,
        "n": pl.UInt32,
        "n_error": pl.UInt32,
        "n_primary": pl.UInt32,
        "error_rate": pl.Float64,
        "top1": pl.Float64,
        "mae": pl.Float64,
        "spearman": pl.Float64,
        "auc": pl.Float64,
        "confident_error_rate": pl.Float64,
        "ece": pl.Float64,
        "tokens_per_1000": pl.Float64,
        "latency_p50_ms": pl.Float64,
        "latency_p95_ms": pl.Float64,
    }


def prepare_cases(logs: pl.DataFrame) -> pl.DataFrame:
    """ケース単位の pred / correct を付ける。集計と対応あり検定の共通前処理。"""
    cols = set(logs.columns)
    missing = [name for name in _REQUIRED if name not in cols]
    if missing:
        raise MetricsError(f"集計に必須列が無い: {', '.join(missing)}")
    frame = logs
    for name in _OPTIONAL:
        if name not in cols:
            frame = frame.with_columns(pl.lit(None).alias(name))
    gold = pl.col("gold").cast(pl.String)
    has_error = pl.col("error").is_not_null() & (pl.col("error").cast(pl.String) != "")
    pred = (
        pl.when(has_error)
        .then(None)
        .otherwise(pl.col("answer").cast(pl.Float64, strict=False))
    )
    gold_score = gold.replace_strict(
        _SCORE_GOLD_STR, default=None, return_dtype=pl.String
    ).cast(pl.Float64, strict=False)
    gold_noul = gold.replace_strict(
        _NOUL_GOLD_STR, default=None, return_dtype=pl.String
    )
    gold_yes = (
        pl.when(gold_noul.is_in(list(_YES_LABELS)))
        .then(pl.lit(True))
        .when(gold_noul == "no")
        .then(pl.lit(False))
    )
    choice_correct = pl.col("answer").cast(pl.String) == gold
    score_correct = pred.round(0) == gold_score
    noul_correct = (pred >= NOUL_DECISION_THRESHOLD) == gold_yes
    correct = (
        pl.when(has_error)
        .then(pl.lit(False))
        .when(pl.col("task") == "choice")
        .then(choice_correct.fill_null(False))
        .when(pl.col("task") == "score")
        .then(score_correct.fill_null(False))
        .when(pl.col("task") == "noul")
        .then(noul_correct.fill_null(False))
        .otherwise(pl.lit(False))
    )
    noul_conf = pl.max_horizontal(pred, pl.lit(1.0) - pred)
    cal_confidence = (
        pl.when(pl.col("confidence").is_not_null())
        .then(pl.col("confidence"))
        .when(pl.col("task") == "noul")
        .then(noul_conf)
    )
    confident = (
        pl.when(pl.col("task") == "noul")
        .then(
            pred.is_not_null()
            & ((pred <= (1.0 - CONFIDENT_THRESHOLD)) | (pred >= CONFIDENT_THRESHOLD))
        )
        .otherwise(pl.col("confidence") >= CONFIDENT_THRESHOLD)
        .fill_null(False)
    )
    prepared = frame.with_columns(
        pred=pred,
        gold_score=gold_score,
        gold_yes=gold_yes,
        has_error=has_error,
        correct=correct,
        cal_confidence=cal_confidence,
        confident_error=confident & ~correct,
    )
    _require_unit_interval(prepared)
    score_valid = (
        pl.col("pred").is_not_null()
        & pl.col("gold_score").is_not_null()
        & ~pl.col("has_error")
    )
    noul_valid = (
        pl.col("pred").is_not_null()
        & pl.col("gold_yes").is_not_null()
        & ~pl.col("has_error")
    )
    return prepared.with_columns(
        primary_valid=(
            pl.when(pl.col("task") == "choice")
            .then(pl.lit(True))
            .when(pl.col("task") == "score")
            .then(score_valid)
            .when(pl.col("task") == "noul")
            .then(noul_valid)
            .otherwise(pl.lit(False))
        )
    )


def _require_unit_interval(prepared: pl.DataFrame) -> None:
    """Noul の予測と confidence は有限な [0, 1]。Score の連続値は対象外。"""
    _reject_outside_unit(
        prepared.filter(pl.col("confidence").is_not_null())["confidence"],
        "confidence",
    )
    noul = prepared.filter(
        (pl.col("task") == "noul") & pl.col("pred").is_not_null() & ~pl.col("has_error")
    )
    if noul.height > 0:
        _reject_outside_unit(noul["pred"], "noul")


def _reject_outside_unit(values: pl.Series, name: str) -> None:
    if values.len() == 0:
        return
    numeric = values.cast(pl.Float64, strict=False)
    bad = (
        numeric.is_null()
        | numeric.is_nan()
        | numeric.is_infinite()
        | (numeric < 0)
        | (numeric > 1)
    )
    if bool(bad.any()):
        raise MetricsError(f"{name} は有限な 0〜1 でなければならない")


def _top1_expr() -> pl.Expr:
    return pl.when(pl.col("task").first() == "choice").then(pl.col("correct").mean())


def _mae_expr() -> pl.Expr:
    abs_err = (pl.col("pred") - pl.col("gold_score")).abs()
    return pl.when(pl.col("task").first() == "score").then(abs_err.mean())


def _spearman_expr() -> pl.Expr:
    return pl.when(pl.col("task").first() == "score").then(
        pl.corr("pred", "gold_score", method="spearman")
    )


def _auc_by_group(prepared: pl.DataFrame) -> pl.DataFrame:
    noul = prepared.filter(
        (pl.col("task") == "noul")
        & pl.col("pred").is_not_null()
        & pl.col("gold_yes").is_not_null()
        & ~pl.col("has_error")
    )
    empty = pl.DataFrame(
        schema={**{k: pl.String for k in GROUP_KEYS}, "auc": pl.Float64}
    )
    if noul.height == 0:
        return empty
    pos = noul.filter(pl.col("gold_yes")).select(
        *GROUP_KEYS, pl.col("pred").alias("pos")
    )
    neg = noul.filter(~pl.col("gold_yes")).select(
        *GROUP_KEYS, pl.col("pred").alias("neg")
    )
    if pos.height == 0 or neg.height == 0:
        return empty
    pairs = pos.join(neg, on=list(GROUP_KEYS), how="inner")
    if pairs.height == 0:
        return empty
    wins = (pl.col("pos") > pl.col("neg")).cast(pl.Float64)
    ties = (pl.col("pos") == pl.col("neg")).cast(pl.Float64)
    return pairs.group_by(list(GROUP_KEYS)).agg(auc=(wins + 0.5 * ties).mean())


def _ece_by_group(prepared: pl.DataFrame) -> pl.DataFrame:
    scored = prepared.filter(
        pl.col("cal_confidence").is_not_null() & pl.col("correct").is_not_null()
    )
    empty = pl.DataFrame(
        schema={**{k: pl.String for k in GROUP_KEYS}, "ece": pl.Float64}
    )
    if scored.height == 0:
        return empty
    last_bin = ECE_BINS - 1
    binned = scored.with_columns(
        bin=(pl.col("cal_confidence") * ECE_BINS)
        .floor()
        .clip(0, last_bin)
        .cast(pl.Int8)
    )
    totals = binned.group_by(list(GROUP_KEYS)).agg(n_cal=pl.len())
    per_bin = binned.group_by([*GROUP_KEYS, "bin"]).agg(
        n_bin=pl.len(),
        acc=pl.col("correct").mean(),
        conf=pl.col("cal_confidence").mean(),
    )
    weighted = per_bin.join(totals, on=list(GROUP_KEYS), how="inner").with_columns(
        w=(pl.col("n_bin") / pl.col("n_cal")) * (pl.col("acc") - pl.col("conf")).abs()
    )
    return weighted.group_by(list(GROUP_KEYS)).agg(ece=pl.col("w").sum())
