# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""1 リクエスト 1 行のログ。公開行から本文キーを除く。表は Polars。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from jev_prompts.data.schema import BODY_COLUMNS, SPLITS, TASKS, SplitId, TaskId
from jev_prompts.prompts.catalog import CONDITIONS, ConditionId

REQUEST_LOG_COLUMNS: Final[tuple[str, ...]] = (
    "case_id",
    "task",
    "condition",
    "split",
    "model",
    "provider",
    "request_id",
    "routing_json",
    "state_json",
    "question_json",
    "answer",
    "probabilities",
    "confidence",
    "usage_tokens",
    "latency_ms",
    "gold",
    "error",
    "content_hash",
)

PUBLISHED_COLUMNS: Final[tuple[str, ...]] = tuple(
    c for c in REQUEST_LOG_COLUMNS if c not in BODY_COLUMNS
)

_LOCAL_SCHEMA: Final[dict[str, pl.DataType]] = {
    "case_id": pl.String,
    "task": pl.String,
    "condition": pl.String,
    "split": pl.String,
    "model": pl.String,
    "provider": pl.String,
    "request_id": pl.String,
    "routing_json": pl.String,
    "state_json": pl.String,
    "question_json": pl.String,
    "answer": pl.String,
    "probabilities": pl.String,
    "confidence": pl.Float64,
    "usage_tokens": pl.Int64,
    "latency_ms": pl.Float64,
    "gold": pl.String,
    "error": pl.String,
    "content_hash": pl.String,
}

_PUBLISHED_SCHEMA: Final[dict[str, pl.DataType]] = {
    name: dtype for name, dtype in _LOCAL_SCHEMA.items() if name in PUBLISHED_COLUMNS
}


class LogSchemaError(ValueError):
    """ログの列が契約と違う、probabilities が無い、または本文が公開行に残る。"""


@dataclass(frozen=True, slots=True)
class RequestLog:
    """再集計の正本（ローカル）。`probabilities` は必須。"""

    case_id: str
    task: TaskId
    condition: ConditionId
    split: SplitId
    probabilities: dict[str, float]
    gold: str | int
    content_hash: str
    model: str | None = None
    provider: str | None = None
    request_id: str | None = None
    routing_json: Mapping[str, Any] | None = None
    state_json: Mapping[str, Any] | list[Any] | str | None = None
    question_json: Mapping[str, Any] | list[Any] | str | None = None
    answer: str | float | None = None
    confidence: float | None = None
    usage_tokens: int | None = None
    latency_ms: float | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.task not in TASKS:
            raise LogSchemaError(f"未知の task: {self.task}")
        if self.condition not in CONDITIONS:
            raise LogSchemaError(f"未知の condition: {self.condition}")
        if self.split not in SPLITS:
            raise LogSchemaError(f"未知の split: {self.split}")
        _parse_probabilities(self.probabilities)

    @classmethod
    def failed(
        cls,
        *,
        case_id: str,
        task: TaskId,
        condition: ConditionId,
        split: SplitId,
        gold: str | int,
        content_hash: str,
        error: str,
        state_json: Mapping[str, Any] | list[Any] | str | None = None,
        question_json: Mapping[str, Any] | list[Any] | str | None = None,
        routing_json: Mapping[str, Any] | None = None,
    ) -> RequestLog:
        return cls(
            case_id=case_id,
            task=task,
            condition=condition,
            split=split,
            probabilities={},
            gold=gold,
            content_hash=content_hash,
            state_json=state_json,
            question_json=question_json,
            routing_json=routing_json,
            error=error,
        )


def _json_cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_probabilities(raw: Any) -> dict[str, float]:
    """JSON オブジェクトで値がすべて数値。null・配列・非数値は拒否する。"""
    if raw is None:
        raise LogSchemaError("probabilities は必須")
    if isinstance(raw, str):
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LogSchemaError("probabilities が JSON ではない") from exc
    else:
        parsed = raw
    if parsed is None:
        raise LogSchemaError("probabilities は必須")
    if not isinstance(parsed, dict):
        raise LogSchemaError("probabilities は必須のオブジェクト")
    out: dict[str, float] = {}
    for key, value in parsed.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LogSchemaError(f"probabilities.{key} が数値ではない")
        out[str(key)] = float(value)
    return out


def _require_probabilities_cell(raw: Any) -> str:
    parsed = _parse_probabilities(raw)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_probabilities_column(df: pl.DataFrame) -> None:
    if "probabilities" not in df.columns:
        raise LogSchemaError("probabilities は必須")
    if df.height == 0:
        return
    if df["probabilities"].null_count() > 0:
        raise LogSchemaError("probabilities は必須")
    for value in df["probabilities"].to_list():
        _parse_probabilities(value)


def request_log_row(log: RequestLog) -> dict[str, Any]:
    return {
        "case_id": log.case_id,
        "task": log.task,
        "condition": log.condition,
        "split": log.split,
        "model": log.model,
        "provider": log.provider,
        "request_id": log.request_id,
        "routing_json": _json_cell(log.routing_json),
        "state_json": _json_cell(log.state_json),
        "question_json": _json_cell(log.question_json),
        "answer": _json_cell(log.answer),
        "probabilities": _require_probabilities_cell(log.probabilities),
        "confidence": log.confidence,
        "usage_tokens": log.usage_tokens,
        "latency_ms": log.latency_ms,
        "gold": None if log.gold is None else str(log.gold),
        "error": log.error,
        "content_hash": log.content_hash,
    }


def published_row(log: RequestLog) -> dict[str, Any]:
    row = request_log_row(log)
    return {name: row[name] for name in PUBLISHED_COLUMNS}


def local_frame(logs: list[RequestLog]) -> pl.DataFrame:
    if not logs:
        return pl.DataFrame(schema=_LOCAL_SCHEMA)
    df = pl.DataFrame([request_log_row(log) for log in logs], schema=_LOCAL_SCHEMA)
    validate_local_logs(df)
    return df.select(list(REQUEST_LOG_COLUMNS))


def published_frame(logs: list[RequestLog]) -> pl.DataFrame:
    if not logs:
        return pl.DataFrame(schema=_PUBLISHED_SCHEMA)
    df = pl.DataFrame([published_row(log) for log in logs], schema=_PUBLISHED_SCHEMA)
    validate_published_records(df)
    return df.select(list(PUBLISHED_COLUMNS))


def to_published(df: pl.DataFrame) -> pl.DataFrame:
    """ローカルログから本文キーを除いた公開行にする。"""
    validate_local_logs(df)
    published = df.select(list(PUBLISHED_COLUMNS))
    validate_published_records(published)
    return published


def _column_names(df: pl.DataFrame) -> list[str]:
    return list(df.columns)


def validate_local_logs(df: pl.DataFrame) -> None:
    cols = set(_column_names(df))
    missing = [c for c in REQUEST_LOG_COLUMNS if c not in cols]
    if missing:
        raise LogSchemaError(f"ローカルログに必須列が無い: {', '.join(missing)}")
    extra = sorted(cols - set(REQUEST_LOG_COLUMNS))
    if extra:
        raise LogSchemaError(f"ローカルログの未知の列: {', '.join(extra)}")
    _validate_probabilities_column(df)


def validate_published_records(df: pl.DataFrame) -> None:
    cols = set(_column_names(df))
    body = sorted(cols & BODY_COLUMNS)
    if body:
        raise LogSchemaError(
            f"公開行に本文フィールドを書いてはいけない: {', '.join(body)}"
        )
    missing = [c for c in PUBLISHED_COLUMNS if c not in cols]
    if missing:
        raise LogSchemaError(f"公開行に必須列が無い: {', '.join(missing)}")
    extra = sorted(cols - set(PUBLISHED_COLUMNS))
    if extra:
        raise LogSchemaError(f"公開行の未知の列: {', '.join(extra)}")
    _validate_probabilities_column(df)


def write_local_logs(df: pl.DataFrame, path: Path) -> None:
    validate_local_logs(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(REQUEST_LOG_COLUMNS)).write_ndjson(path)


def read_local_logs(path: Path) -> pl.DataFrame:
    df = pl.read_ndjson(path, schema=_LOCAL_SCHEMA)
    validate_local_logs(df)
    return df.select(list(REQUEST_LOG_COLUMNS))


def write_published_records(df: pl.DataFrame, path: Path) -> None:
    validate_published_records(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(PUBLISHED_COLUMNS)).write_ndjson(path)


def read_published_records(path: Path) -> pl.DataFrame:
    df = pl.read_ndjson(path, schema=_PUBLISHED_SCHEMA)
    validate_published_records(df)
    return df.select(list(PUBLISHED_COLUMNS))
