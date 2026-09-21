# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""ケースごとに全条件を連続実行する。条件ネストでは回さない。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from jev_prompts.data.schema import SPLITS, TASKS, SplitId, TaskId
from jev_prompts.prompts.catalog import CONDITIONS, ConditionId
from jev_prompts.runners.schema import (
    LogSchemaError,
    RequestLog,
    local_frame,
    to_published,
)


@dataclass(frozen=True, slots=True)
class RunCase:
    case_id: str
    task: TaskId
    split: SplitId
    gold: str | int
    content_hash: str


ExecuteFn = Callable[[RunCase, ConditionId], RequestLog]


def as_run_case(case: RunCase | Mapping[str, Any]) -> RunCase:
    if isinstance(case, RunCase):
        return case
    try:
        task = case["task"]
        split = case["split"]
        case_id = case["case_id"]
        gold = case["gold"]
        content_hash = case["content_hash"]
    except KeyError as exc:
        raise LogSchemaError(f"ケースに必須キーが無い: {exc.args[0]}") from exc
    if task not in TASKS:
        raise LogSchemaError(f"未知の task: {task}")
    if split not in SPLITS:
        raise LogSchemaError(f"未知の split: {split}")
    if not isinstance(case_id, str) or not case_id:
        raise LogSchemaError("case_id が空")
    if not isinstance(content_hash, str) or not content_hash:
        raise LogSchemaError("content_hash が空")
    return RunCase(
        case_id=case_id,
        task=task,
        split=split,
        gold=gold,
        content_hash=content_hash,
    )


def _require_condition(condition: str) -> ConditionId:
    if condition not in CONDITIONS:
        raise LogSchemaError(f"未知の condition: {condition}")
    return condition


def iter_case_conditions(
    cases: Sequence[RunCase | Mapping[str, Any]],
    conditions: Sequence[str] | None = None,
) -> Iterator[tuple[RunCase, ConditionId]]:
    """ケース外側・条件内側。`(条件, ケース)` の順には展開しない。"""
    conds = CONDITIONS if conditions is None else tuple(conditions)
    if not conds:
        raise LogSchemaError("conditions が空")
    parsed_conditions = tuple(_require_condition(item) for item in conds)
    for case in cases:
        parsed = as_run_case(case)
        for condition in parsed_conditions:
            yield parsed, condition


def completed_pairs(frame: pl.DataFrame) -> frozenset[tuple[str, str]]:
    """再開用。(case_id, condition) の集合。"""
    if frame.height == 0 or "case_id" not in frame.columns:
        return frozenset()
    if "condition" not in frame.columns:
        return frozenset()
    return frozenset(
        zip(frame["case_id"].to_list(), frame["condition"].to_list(), strict=True)
    )


def run_experiment(
    cases: Sequence[RunCase | Mapping[str, Any]],
    execute: ExecuteFn,
    *,
    conditions: Sequence[str] | None = None,
    skip: Iterable[tuple[str, str]] | None = None,
    on_row: Callable[[RequestLog], None] | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """1 リクエスト 1 行のローカルログと、本文なしの公開行を返す。"""
    seen = frozenset(skip) if skip is not None else frozenset()
    logs: list[RequestLog] = []
    for case, condition in iter_case_conditions(cases, conditions):
        if (case.case_id, condition) in seen:
            continue
        try:
            log = execute(case, condition)
        except Exception as exc:
            log = RequestLog.failed(
                case_id=case.case_id,
                task=case.task,
                condition=condition,
                split=case.split,
                gold=case.gold,
                content_hash=case.content_hash,
                error=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(log, RequestLog):
            raise TypeError("execute は RequestLog を返す")
        logs.append(log)
        if on_row is not None:
            on_row(log)
    local = local_frame(logs)
    return local, to_published(local)
