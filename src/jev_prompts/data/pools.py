# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""raw レコードから抽出プールを組む。境界フラグは設計書の事前宣言に従う。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import polars as pl

from jev_prompts.config import MAIN_SEED
from jev_prompts.data.extract import ExtractConfig, extract_cases
from jev_prompts.data.fetch import FetchError, load_task_records
from jev_prompts.data.ledger import write_ledger
from jev_prompts.data.schema import TASKS, TaskId

CHOICE_BOUNDARY_LABELS: Final[frozenset[str]] = frozenset(
    {
        "card_payment_fee_charged",
        "transaction_fee_charged",
        "cash_withdrawal_charge",
    }
)
SCORE_BOUNDARY_LABELS: Final[frozenset[str]] = frozenset({"S", "C", "1", "2"})
NOUL_BOUNDARY_LABELS: Final[frozenset[str]] = frozenset({"ham", "no"})

_BODY: Final[dict[TaskId, tuple[str, ...]]] = {
    "choice": ("text",),
    "score": ("query", "title", "description"),
    "noul": ("message",),
}


class PoolError(FetchError):
    """抽出プールが足りない、または gold が無い。"""


def is_boundary(task: TaskId, gold: object) -> bool:
    label = str(gold)
    if task == "choice":
        return label in CHOICE_BOUNDARY_LABELS
    if task == "score":
        return label in SCORE_BOUNDARY_LABELS
    return label in NOUL_BOUNDARY_LABELS


def build_pool(task: TaskId, records: Mapping[str, Mapping[str, Any]]) -> pl.DataFrame:
    """content_hash に使う本文列と gold / boundary を持つ表を返す。"""
    rows: list[dict[str, Any]] = []
    for record in records.values():
        gold = record.get("gold")
        if gold is None or str(gold) == "":
            raise PoolError(f"{task} の gold が無い: {record.get('source_id')}")
        source_id = record.get("source_id")
        if not source_id:
            raise PoolError(f"{task} の source_id が無い")
        row: dict[str, Any] = {
            "source_id": str(source_id),
            "gold": gold,
            "boundary": is_boundary(task, gold),
        }
        for key in _BODY[task]:
            if key not in record:
                raise PoolError(f"{task} に {key} が無い: {source_id}")
            row[key] = record[key]
        rows.append(row)
    if not rows:
        raise PoolError(f"{task} のプールが空")
    return pl.DataFrame(rows)


def default_extract_config(seed: int = MAIN_SEED) -> ExtractConfig:
    return ExtractConfig(seed=seed)


def extract_ledgers(
    raw_root: Path,
    cases_root: Path,
    *,
    config: ExtractConfig | None = None,
) -> list[Path]:
    """課題ごとに 100 件を切り出し、本文なしの台帳を書く。"""
    cfg = config or default_extract_config()
    written: list[Path] = []
    cases_root.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        records = load_task_records(raw_root, task)
        pool = build_pool(task, records)
        frame = extract_cases(pool, task=task, config=cfg)
        path = cases_root / f"{task}.jsonl"
        write_ledger(frame, path)
        written.append(path)
    return written
