# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""較正の確率を 10 ビンに分けた表。"""

from __future__ import annotations

from typing import Final

import polars as pl

from jev_prompts.config import ECE_BINS
from jev_prompts.metrics import GROUP_KEYS, aggregate_metrics, prepare_cases

CALIBRATION_COLUMNS: Final[tuple[str, ...]] = (
    *GROUP_KEYS,
    "bin",
    "bin_low",
    "bin_high",
    "n",
    "mean_probability",
    "accuracy",
    "ece",
)


def calibration_table(logs: pl.DataFrame) -> pl.DataFrame:
    """条件ごとのビン別正解率。空ビンも 10 本そろえる。"""
    prepared = prepare_cases(logs)
    scored = prepared.filter(pl.col("cal_probability").is_not_null())
    if scored.height == 0:
        return pl.DataFrame(schema=_schema())
    last_bin = ECE_BINS - 1
    binned = scored.with_columns(
        bin=(pl.col("cal_probability") * ECE_BINS)
        .floor()
        .clip(0, last_bin)
        .cast(pl.Int8)
    )
    occupied = binned.group_by([*GROUP_KEYS, "bin"]).agg(
        n=pl.len(),
        accuracy=pl.col("correct").mean(),
        mean_probability=pl.col("cal_probability").mean(),
    )
    grid = _bin_grid(scored)
    ece = aggregate_metrics(logs).select(*GROUP_KEYS, "ece")
    return (
        grid.join(occupied, on=[*GROUP_KEYS, "bin"], how="left")
        .join(ece, on=list(GROUP_KEYS), how="left")
        .with_columns(
            n=pl.col("n").fill_null(0),
            bin_low=pl.col("bin").cast(pl.Float64) / ECE_BINS,
            bin_high=(pl.col("bin").cast(pl.Float64) + 1.0) / ECE_BINS,
        )
        .select(list(CALIBRATION_COLUMNS))
        .sort([*GROUP_KEYS, "bin"])
    )


def _bin_grid(scored: pl.DataFrame) -> pl.DataFrame:
    groups = scored.select(list(GROUP_KEYS)).unique(maintain_order=True)
    bins = pl.DataFrame({"bin": list(range(ECE_BINS))}, schema={"bin": pl.Int8})
    return groups.join(bins, how="cross")


def _schema() -> dict[str, pl.DataType]:
    return {
        "task": pl.String,
        "condition": pl.String,
        "split": pl.String,
        "bin": pl.Int8,
        "bin_low": pl.Float64,
        "bin_high": pl.Float64,
        "n": pl.UInt32,
        "mean_probability": pl.Float64,
        "accuracy": pl.Float64,
        "ece": pl.Float64,
    }
