# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""A の質問を 1 回まとめ vs n 回分割する別ラン。精度比較には混ぜない。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, Literal

import polars as pl

from jev_prompts.runners.experiment import RunCase, as_run_case
from jev_prompts.runners.schema import (
    LogSchemaError,
    RequestLog,
    local_frame,
    write_local_logs,
)

type FanoutPath = Literal["batched", "split"]
type FanoutExecuteFn = Callable[[RunCase, Mapping[str, Mapping[str, Any]]], RequestLog]

FANOUT_PATHS: Final[tuple[FanoutPath, ...]] = ("batched", "split")
EVAL_LOG_FILENAME: Final[str] = "eval.jsonl"
FANOUT_BATCHED_LOG_FILENAME: Final[str] = "fanout-batched.jsonl"
FANOUT_SPLIT_LOG_FILENAME: Final[str] = "fanout-split.jsonl"

_FANOUT_ROUTING_KEY: Final[str] = "fanout_path"
_FANOUT_QUESTION_KEY: Final[str] = "fanout_question_id"


@dataclass(frozen=True, slots=True)
class FanoutComparison:
    """コスト・遅延・答えの一致率。精度指標ではない。"""

    n_cases: int
    n_questions: int
    batched_requests: int
    split_requests: int
    batched_usage_tokens: int
    split_usage_tokens: int
    batched_latency_ms: float
    split_latency_ms: float
    matched: int
    compared: int
    match_rate: float | None


def require_questions(
    questions: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(questions, Mapping) or not questions:
        raise LogSchemaError("fan-out の questions が空")
    out: dict[str, dict[str, Any]] = {}
    for qid, question in questions.items():
        if not qid:
            raise LogSchemaError("question id が空")
        if not isinstance(question, Mapping):
            raise LogSchemaError(f"question がオブジェクトではない: {qid}")
        out[str(qid)] = dict(question)
    return out


def split_questions(
    questions: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], ...]:
    parsed = require_questions(questions)
    return tuple({qid: question} for qid, question in parsed.items())


def eval_log_path(directory: Path) -> Path:
    return directory / EVAL_LOG_FILENAME


def fanout_log_paths(directory: Path) -> tuple[Path, Path]:
    batched = directory / FANOUT_BATCHED_LOG_FILENAME
    split = directory / FANOUT_SPLIT_LOG_FILENAME
    if batched == split:
        raise LogSchemaError("fan-out の 2 経路ログが同一ファイルになる")
    eval_path = eval_log_path(directory)
    if batched == eval_path or split == eval_path:
        raise LogSchemaError("fan-out ログが本ランの eval ログと同じパス")
    return batched, split


def is_fanout_row(routing_json: Any) -> bool:
    parsed = _parse_routing(routing_json)
    return parsed.get(_FANOUT_ROUTING_KEY) in FANOUT_PATHS


def drop_fanout_rows(df: pl.DataFrame) -> pl.DataFrame:
    """本ラン集計用。混入した fan-out 行を除く。"""
    if df.height == 0 or "routing_json" not in df.columns:
        return df
    keep = [not is_fanout_row(raw) for raw in df["routing_json"].to_list()]
    return df.filter(pl.Series("keep_eval", keep))


def run_fanout_batched(
    cases: Sequence[RunCase | Mapping[str, Any]],
    questions: Mapping[str, Mapping[str, Any]],
    execute: FanoutExecuteFn,
) -> pl.DataFrame:
    parsed_questions = require_questions(questions)
    logs: list[RequestLog] = []
    for case in cases:
        parsed = as_run_case(case)
        logs.append(_execute_slice(parsed, parsed_questions, execute, path="batched"))
    return local_frame(logs)


def run_fanout_split(
    cases: Sequence[RunCase | Mapping[str, Any]],
    questions: Mapping[str, Mapping[str, Any]],
    execute: FanoutExecuteFn,
) -> pl.DataFrame:
    slices = split_questions(questions)
    logs: list[RequestLog] = []
    for case in cases:
        parsed = as_run_case(case)
        for slice_questions in slices:
            qid = next(iter(slice_questions))
            logs.append(
                _execute_slice(
                    parsed,
                    slice_questions,
                    execute,
                    path="split",
                    question_id=qid,
                )
            )
    return local_frame(logs)


def write_fanout_logs(
    batched: pl.DataFrame,
    split: pl.DataFrame,
    directory: Path,
) -> tuple[Path, Path]:
    batched_path, split_path = fanout_log_paths(directory)
    write_local_logs(batched, batched_path)
    write_local_logs(split, split_path)
    return batched_path, split_path


def compare_fanout(
    batched: pl.DataFrame,
    split: pl.DataFrame,
    *,
    n_questions: int,
) -> FanoutComparison:
    batched_answers = _answers_by_case_question(batched)
    split_answers = _answers_by_case_question(split)
    keys = sorted(set(batched_answers) & set(split_answers))
    matched = sum(1 for key in keys if batched_answers[key] == split_answers[key])
    compared = len(keys)
    return FanoutComparison(
        n_cases=_n_cases(batched, split),
        n_questions=n_questions,
        batched_requests=batched.height,
        split_requests=split.height,
        batched_usage_tokens=_sum_int(batched, "usage_tokens"),
        split_usage_tokens=_sum_int(split, "usage_tokens"),
        batched_latency_ms=_sum_float(batched, "latency_ms"),
        split_latency_ms=_sum_float(split, "latency_ms"),
        matched=matched,
        compared=compared,
        match_rate=None if compared == 0 else matched / compared,
    )


def run_fanout_pair(
    cases: Sequence[RunCase | Mapping[str, Any]],
    questions: Mapping[str, Mapping[str, Any]],
    execute: FanoutExecuteFn,
    *,
    log_dir: Path | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, FanoutComparison, Path | None, Path | None]:
    parsed_questions = require_questions(questions)
    batched = run_fanout_batched(cases, parsed_questions, execute)
    split = run_fanout_split(cases, parsed_questions, execute)
    comparison = compare_fanout(batched, split, n_questions=len(parsed_questions))
    batched_path: Path | None = None
    split_path: Path | None = None
    if log_dir is not None:
        batched_path, split_path = write_fanout_logs(batched, split, log_dir)
    return batched, split, comparison, batched_path, split_path


def _execute_slice(
    case: RunCase,
    questions: Mapping[str, Mapping[str, Any]],
    execute: FanoutExecuteFn,
    *,
    path: FanoutPath,
    question_id: str | None = None,
) -> RequestLog:
    try:
        log = execute(case, questions)
    except Exception as exc:
        log = RequestLog.failed(
            case_id=case.case_id,
            task=case.task,
            condition="A",
            split=case.split,
            gold=case.gold,
            content_hash=case.content_hash,
            error=f"{type(exc).__name__}: {exc}",
            question_json=dict(questions),
        )
    if not isinstance(log, RequestLog):
        raise TypeError("execute は RequestLog を返す")
    return _stamp_fanout(log, path, question_id)


def _stamp_fanout(
    log: RequestLog, path: FanoutPath, question_id: str | None
) -> RequestLog:
    routing: dict[str, Any] = {}
    if isinstance(log.routing_json, Mapping):
        routing.update(log.routing_json)
    routing[_FANOUT_ROUTING_KEY] = path
    if question_id is None:
        routing.pop(_FANOUT_QUESTION_KEY, None)
    else:
        routing[_FANOUT_QUESTION_KEY] = question_id
    return replace(log, routing_json=routing)


def _parse_routing(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _question_ids(raw: Any) -> tuple[str, ...]:
    parsed = _parse_json_object(raw)
    if parsed is None:
        return ()
    return tuple(str(key) for key in parsed)


def _row_answers(row: Mapping[str, Any]) -> dict[str, str] | None:
    if row.get("error"):
        return None
    qids = _question_ids(row.get("question_json"))
    if not qids:
        return None
    answer = row.get("answer")
    parsed = _parse_json_object(answer)
    if parsed is not None:
        return {
            str(key): "" if value is None else str(value)
            for key, value in parsed.items()
        }
    if len(qids) != 1 or answer is None:
        return None
    return {qids[0]: str(answer)}


def _answers_by_case_question(df: pl.DataFrame) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    if df.height == 0:
        return out
    records = df.select(["case_id", "question_json", "answer", "error"]).iter_rows(
        named=True
    )
    for row in records:
        answers = _row_answers(row)
        if answers is None:
            continue
        case_id = str(row["case_id"])
        for qid, value in answers.items():
            out[(case_id, qid)] = value
    return out


def _n_cases(batched: pl.DataFrame, split: pl.DataFrame) -> int:
    ids: set[str] = set()
    if "case_id" in batched.columns:
        ids.update(str(item) for item in batched["case_id"].to_list())
    if "case_id" in split.columns:
        ids.update(str(item) for item in split["case_id"].to_list())
    return len(ids)


def _sum_int(df: pl.DataFrame, column: str) -> int:
    if df.height == 0 or column not in df.columns:
        return 0
    total = 0
    for value in df[column].to_list():
        if value is None:
            continue
        total += int(value)
    return total


def _sum_float(df: pl.DataFrame, column: str) -> float:
    if df.height == 0 or column not in df.columns:
        return 0.0
    total = 0.0
    for value in df[column].to_list():
        if value is None:
            continue
        total += float(value)
    return total
