# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""投機的 fan-out は精度比較と同一ランに入れない。"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from jev_prompts.clients import JevResult, OpenRouterClient
from jev_prompts.prompts.catalog import load_bundle
from jev_prompts.runners.experiment import RunCase
from jev_prompts.runners.payload import materialize_state

type FanoutMode = Literal["batched", "split"]


class FanoutError(ValueError):
    """fan-out の入力が空、または比較できない。"""


@dataclass(frozen=True, slots=True)
class FanoutCall:
    mode: FanoutMode
    questions: dict[str, Any]
    question_id: str | None


@dataclass(frozen=True, slots=True)
class FanoutCaseResult:
    case_id: str
    task: str
    batched_ms: float
    split_ms: float
    batched_tokens: int | None
    split_tokens: int | None
    agreed: int
    compared: int


def iter_fanout_calls(questions: Mapping[str, Mapping[str, Any]]) -> list[FanoutCall]:
    """1 回にまとめる呼び出しと、質問ごとの分割呼び出し。"""
    if not questions:
        raise FanoutError("questions が空")
    packed = {str(qid): dict(item) for qid, item in questions.items()}
    calls = [FanoutCall("batched", packed, None)]
    for qid, item in packed.items():
        calls.append(FanoutCall("split", {qid: item}, qid))
    return calls


def _usage_total(result: JevResult) -> int | None:
    usage = result.usage or {}
    value = usage.get("total_tokens", usage.get("totalTokens"))
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)
    prompt = usage.get("prompt_tokens", usage.get("promptTokens"))
    completion = usage.get("completion_tokens", usage.get("completionTokens"))
    parts = [
        int(item)
        for item in (prompt, completion)
        if isinstance(item, int | float) and not isinstance(item, bool)
    ]
    return sum(parts) if parts else None


def _answer_tuple(answer: Any) -> tuple[Any, Any, Any]:
    return (
        getattr(answer, "choice", None),
        getattr(answer, "score", None),
        getattr(answer, "noul", None),
    )


def agreement(
    batched: JevResult, split_by_id: Mapping[str, JevResult]
) -> tuple[int, int]:
    agreed = 0
    compared = 0
    for qid, left in batched.answers.items():
        right_result = split_by_id.get(qid)
        if right_result is None or qid not in right_result.answers:
            continue
        compared += 1
        if _answer_tuple(left) == _answer_tuple(right_result.answers[qid]):
            agreed += 1
    return agreed, compared


def run_fanout_case(
    client: OpenRouterClient,
    case: RunCase,
    record: Mapping[str, Any],
    *,
    prompts_root: Any = None,
) -> FanoutCaseResult:
    """条件 A の質問群を、まとめて 1 回と分割 n 回で実行する。"""
    bundle = load_bundle(case.task, "A", root=prompts_root)
    if bundle.state is None or bundle.questions is None:
        raise FanoutError(f"{case.task}/A に questions が無い")
    state = materialize_state(case.task, bundle.state, record)
    calls = iter_fanout_calls(bundle.questions)
    batched: JevResult | None = None
    split: dict[str, JevResult] = {}
    batched_ms = 0.0
    split_ms = 0.0
    batched_tokens: int | None = None
    split_tokens = 0
    saw_split_tokens = False
    for call in calls:
        started = time.perf_counter()
        result = client.system_one(state=state, questions=call.questions)
        elapsed = (time.perf_counter() - started) * 1000
        tokens = _usage_total(result)
        if call.mode == "batched":
            batched = result
            batched_ms = elapsed
            batched_tokens = tokens
        else:
            assert call.question_id is not None
            split[call.question_id] = result
            split_ms += elapsed
            if tokens is not None:
                split_tokens += tokens
                saw_split_tokens = True
    if batched is None:
        raise FanoutError("batched の結果が無い")
    agreed, compared = agreement(batched, split)
    return FanoutCaseResult(
        case_id=case.case_id,
        task=case.task,
        batched_ms=batched_ms,
        split_ms=split_ms,
        batched_tokens=batched_tokens,
        split_tokens=split_tokens if saw_split_tokens else None,
        agreed=agreed,
        compared=compared,
    )


def run_fanout(
    client: OpenRouterClient,
    cases: list[tuple[RunCase, dict[str, Any]]],
    *,
    prompts_root: Any = None,
) -> list[FanoutCaseResult]:
    if not cases:
        raise FanoutError("fan-out のケースが無い")
    return [
        run_fanout_case(client, case, record, prompts_root=prompts_root)
        for case, record in cases
    ]
