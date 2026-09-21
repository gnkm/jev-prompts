# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""prompts/ の JSON を読む。条件の差分はファイルに置き、実行時に組み立てない。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from jev_prompts.config import PROMPTS_DIR
from jev_prompts.data.schema import TASKS, TaskId

type ConditionId = Literal["A", "B1", "B2", "B3", "C", "L1", "L2", "L3"]

JEV_CONDITIONS: Final[tuple[ConditionId, ...]] = ("A", "B1", "B2", "B3", "C")
LLM_CONDITIONS: Final[tuple[ConditionId, ...]] = ("L1", "L2", "L3")
CONDITIONS: Final[tuple[ConditionId, ...]] = (*JEV_CONDITIONS, *LLM_CONDITIONS)

_KNOWN_KEYS: Final[frozenset[str]] = frozenset(
    {"task", "condition", "state", "questions", "llm_messages"}
)


class CatalogError(ValueError):
    """カタログファイルが無い、または形が契約と違う。"""


@dataclass(frozen=True, slots=True)
class PromptBundle:
    task: TaskId
    condition: ConditionId
    state: dict[str, Any] | None
    questions: dict[str, Any] | None
    llm_messages: list[dict[str, Any]] | None
    source_path: Path


def catalog_path(
    task: TaskId, condition: ConditionId, *, root: Path | None = None
) -> Path:
    base = PROMPTS_DIR if root is None else root
    if condition in LLM_CONDITIONS:
        return base / "llm" / task / f"{condition}.json"
    return base / task / f"{condition}.json"


def load_bundle(task: str, condition: str, *, root: Path | None = None) -> PromptBundle:
    """指定した課題・条件の JSON をそのまま返す。欠けた questions は補わない。"""
    task_id = _require_task(task)
    condition_id = _require_condition(condition)
    path = catalog_path(task_id, condition_id, root=root)
    if not path.is_file():
        raise CatalogError(f"カタログが無い: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"カタログが JSON ではない: {path}") from exc
    if not isinstance(raw, dict):
        raise CatalogError(f"カタログは JSON オブジェクトである: {path}")
    return _parse_bundle(raw, task_id, condition_id, path)


def load_all(*, root: Path | None = None) -> list[PromptBundle]:
    return [
        load_bundle(task, condition, root=root)
        for task in TASKS
        for condition in CONDITIONS
    ]


def sole_question(bundle: PromptBundle) -> dict[str, Any]:
    if bundle.questions is None:
        raise CatalogError(f"{bundle.condition} に questions が無い")
    if len(bundle.questions) != 1:
        raise CatalogError(
            f"{bundle.task}/{bundle.condition} の questions は 1 問である: "
            f"{sorted(bundle.questions)}"
        )
    question = next(iter(bundle.questions.values()))
    if not isinstance(question, dict):
        raise CatalogError("question はオブジェクトである")
    return question


def _require_task(task: str) -> TaskId:
    if task not in TASKS:
        raise CatalogError(f"未知の課題: {task}")
    return task


def _require_condition(condition: str) -> ConditionId:
    if condition not in CONDITIONS:
        raise CatalogError(f"未知の条件: {condition}")
    return condition


def _parse_bundle(
    raw: dict[str, Any],
    task: TaskId,
    condition: ConditionId,
    path: Path,
) -> PromptBundle:
    extra = sorted(set(raw) - _KNOWN_KEYS)
    if extra:
        raise CatalogError(f"未知のキー: {', '.join(extra)} ({path})")
    if raw.get("task") != task:
        raise CatalogError(f"task がパスと一致しない: {path}")
    if raw.get("condition") != condition:
        raise CatalogError(f"condition がパスと一致しない: {path}")

    state = raw.get("state")
    questions = raw.get("questions")
    llm_messages = raw.get("llm_messages")

    if condition in JEV_CONDITIONS:
        if not isinstance(state, dict):
            raise CatalogError(f"state がオブジェクトではない: {path}")
        if not isinstance(questions, dict) or not questions:
            raise CatalogError(f"questions が空またはオブジェクトではない: {path}")
        if llm_messages is not None:
            raise CatalogError(f"Jev 条件に llm_messages を置かない: {path}")
        return PromptBundle(
            task=task,
            condition=condition,
            state=state,
            questions=questions,
            llm_messages=None,
            source_path=path,
        )

    if not isinstance(llm_messages, list) or not llm_messages:
        raise CatalogError(f"llm_messages が空または配列ではない: {path}")
    if state is not None or questions is not None:
        raise CatalogError(f"LLM 条件に state / questions を置かない: {path}")
    if not all(isinstance(item, dict) for item in llm_messages):
        raise CatalogError(f"llm_messages の要素はオブジェクトである: {path}")
    return PromptBundle(
        task=task,
        condition=condition,
        state=None,
        questions=None,
        llm_messages=llm_messages,
        source_path=path,
    )
