"""ケース台帳の jsonl を Polars で読み書きする。本文列は拒否する。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from jev_prompts.data.schema import BODY_COLUMNS, LEDGER_COLUMNS, SPLITS, STRATA, TASKS


class LedgerSchemaError(ValueError):
    """台帳の列が許可セットと違う、または本文フィールドを含む。"""


def _column_names(df: pl.DataFrame) -> list[str]:
    return list(df.columns)


def validate_ledger(df: pl.DataFrame) -> None:
    cols = set(_column_names(df))
    body = sorted(cols & BODY_COLUMNS)
    if body:
        raise LedgerSchemaError(
            f"台帳に本文フィールドを書いてはいけない: {', '.join(body)}"
        )
    missing = [c for c in LEDGER_COLUMNS if c not in cols]
    if missing:
        raise LedgerSchemaError(f"台帳に必須列が無い: {', '.join(missing)}")
    extra = sorted(cols - set(LEDGER_COLUMNS))
    if extra:
        raise LedgerSchemaError(f"台帳の未知の列: {', '.join(extra)}")
    if df.height == 0:
        return
    tasks = set(df["task"].unique().to_list())
    unknown_tasks = tasks - set(TASKS)
    if unknown_tasks:
        raise LedgerSchemaError(f"未知の task: {sorted(unknown_tasks)}")
    splits = set(df["split"].unique().to_list())
    unknown_splits = splits - set(SPLITS)
    if unknown_splits:
        raise LedgerSchemaError(f"未知の split: {sorted(unknown_splits)}")
    strata = set(df["stratum"].unique().to_list())
    unknown_strata = strata - set(STRATA)
    if unknown_strata:
        raise LedgerSchemaError(f"未知の stratum: {sorted(unknown_strata)}")


def read_ledger(path: Path) -> pl.DataFrame:
    """本文ファイルを参照せず、台帳 jsonl だけを読む。"""
    df = pl.read_ndjson(path)
    validate_ledger(df)
    return df.select(list(LEDGER_COLUMNS))


def write_ledger(df: pl.DataFrame, path: Path) -> None:
    validate_ledger(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(LEDGER_COLUMNS)).write_ndjson(path)
