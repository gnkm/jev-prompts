# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""ケース本文をカタログの state / LLM メッセージに載せる。"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jev_prompts.data.fetch import (
    FetchError,
    load_task_records,
    source_id_from_case_id,
    verify_ledgers,
)
from jev_prompts.data.ledger import read_ledger
from jev_prompts.data.schema import SPLITS, SplitId, TaskId
from jev_prompts.prompts.catalog import PromptBundle
from jev_prompts.runners.experiment import RunCase

_PLACEHOLDER = "{{%s}}"


class MissingBodyError(FetchError):
    """data/raw に本文が無い、または台帳と照合できない。"""


def require_bodies(raw_root: Path, cases_root: Path) -> int:
    """本文が無ければ失敗する。暗黙の再取得はしない。"""
    try:
        return verify_ledgers(raw_root, cases_root)
    except FetchError as exc:
        raise MissingBodyError(f"本文が無い: {exc}") from exc


def load_run_cases(
    raw_root: Path,
    cases_root: Path,
    *,
    split: SplitId | None = None,
) -> list[tuple[RunCase, dict[str, Any]]]:
    """台帳と raw 本文を照合し、ケースとレコードを返す。"""
    if split is not None and split not in SPLITS:
        raise MissingBodyError(f"未知の split: {split}")
    require_bodies(raw_root, cases_root)
    cache: dict[TaskId, dict[str, dict[str, Any]]] = {}
    loaded: list[tuple[RunCase, dict[str, Any]]] = []
    for path in sorted(cases_root.glob("*.jsonl")):
        if path.stat().st_size == 0:
            continue
        for row in read_ledger(path).to_dicts():
            if split is not None and row["split"] != split:
                continue
            task = row["task"]
            if task not in cache:
                cache[task] = load_task_records(raw_root, task)
            source_id = source_id_from_case_id(str(row["case_id"]))
            record = cache[task][source_id]
            loaded.append(
                (
                    RunCase(
                        case_id=str(row["case_id"]),
                        task=task,
                        split=row["split"],
                        gold=row["gold"],
                        content_hash=str(row["content_hash"]),
                    ),
                    record,
                )
            )
    if not loaded:
        raise MissingBodyError(f"照合できたケースが無い: {cases_root}")
    return loaded


def materialize_state(
    task: TaskId, catalog_state: Mapping[str, Any], record: Mapping[str, Any]
) -> dict[str, Any]:
    """カタログの state をコピーし、ケース本文だけを埋める。"""
    state = copy.deepcopy(dict(catalog_state))
    if task == "choice":
        state["query"] = record["text"]
        return state
    if task == "noul":
        state["message"] = record["message"]
        return state
    state["query"] = record["query"]
    product = dict(state.get("product") or {})
    product["title"] = record["title"]
    product["description"] = record["description"]
    state["product"] = product
    return state


def materialize_messages(
    task: TaskId,
    llm_messages: Sequence[Mapping[str, Any]],
    record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """`{{query}}` などのプレースホルダをケース本文で置換する。"""
    mapping = _placeholders(task, record)
    filled: list[dict[str, Any]] = []
    for message in llm_messages:
        item = dict(message)
        content = item.get("content")
        if isinstance(content, str):
            item["content"] = _fill(content, mapping)
        filled.append(item)
    return filled


def _placeholders(task: TaskId, record: Mapping[str, Any]) -> dict[str, str]:
    if task == "choice":
        return {"query": str(record["text"])}
    if task == "noul":
        return {"message": str(record["message"])}
    title = "" if record.get("title") is None else str(record["title"])
    description = (
        "" if record.get("description") is None else str(record["description"])
    )
    product = "\n".join(part for part in (title, description) if part)
    return {
        "query": str(record["query"]),
        "title": title,
        "description": description,
        "product": product,
    }


def _fill(text: str, mapping: Mapping[str, str]) -> str:
    out = text
    for key, value in mapping.items():
        out = out.replace(_PLACEHOLDER % key, value)
    return out


def request_payload(bundle: PromptBundle, record: Mapping[str, Any]) -> dict[str, Any]:
    """トークン見積もり用に、実際に送る JSON に近い形を返す。"""
    if bundle.questions is not None and bundle.state is not None:
        return {
            "state": materialize_state(bundle.task, bundle.state, record),
            "questions": bundle.questions,
        }
    if bundle.llm_messages is None:
        raise ValueError(f"{bundle.task}/{bundle.condition} に payload が無い")
    return {"messages": materialize_messages(bundle.task, bundle.llm_messages, record)}
