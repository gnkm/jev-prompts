# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""ケースと条件を OpenRouter 呼び出しに載せる。再試行しない。"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from jev_prompts.clients import (
    JevAnswer,
    JevResult,
    LlmResult,
    OpenRouterClient,
    OpenRouterError,
)
from jev_prompts.config import (
    LUNA_MODEL_ID,
    LUNA_PROVIDER,
    SONNET_MODEL_ID,
    SONNET_PROVIDER,
    provider_routing,
)
from jev_prompts.prompts.catalog import JEV_CONDITIONS, load_bundle
from jev_prompts.runners.experiment import RunCase
from jev_prompts.runners.payload import materialize_messages, materialize_state
from jev_prompts.runners.schema import RequestLog


def _usage_tokens(usage: Mapping[str, Any] | None) -> int | None:
    if not usage:
        return None
    for key in ("total_tokens", "totalTokens"):
        value = usage.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return int(value)
    prompt = usage.get("prompt_tokens", usage.get("promptTokens"))
    completion = usage.get("completion_tokens", usage.get("completionTokens"))
    parts = [
        int(item)
        for item in (prompt, completion)
        if isinstance(item, int | float) and not isinstance(item, bool)
    ]
    if not parts:
        return None
    return sum(parts)


def _probabilities(answer: JevAnswer) -> dict[str, float]:
    if answer.probabilities:
        return dict(answer.probabilities)
    if answer.type == "noul" and answer.noul is not None:
        yes = float(answer.noul)
        return {"yes": yes, "no": 1.0 - yes}
    return {}


def _primary_answer(result: JevResult) -> JevAnswer:
    return next(iter(result.answers.values()))


def _from_jev(
    case: RunCase,
    condition: str,
    result: JevResult,
    *,
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
    latency_ms: float,
) -> RequestLog:
    primary = _primary_answer(result)
    value: str | float | None
    if primary.choice is not None:
        value = primary.choice
    elif primary.score is not None:
        value = primary.score
    else:
        value = primary.noul
    return RequestLog(
        case_id=case.case_id,
        task=case.task,
        condition=condition,  # type: ignore[arg-type]
        split=case.split,
        probabilities=_probabilities(primary),
        gold=case.gold,
        content_hash=case.content_hash,
        model=result.model,
        provider=result.provider,
        state_json=state,
        question_json=questions,
        answer=value,
        confidence=primary.confidence,
        usage_tokens=_usage_tokens(result.usage),
        latency_ms=latency_ms,
    )


def _from_llm(
    case: RunCase,
    condition: str,
    result: LlmResult,
    *,
    messages: list[dict[str, Any]],
    routing: Mapping[str, Any],
    latency_ms: float,
) -> RequestLog:
    return RequestLog(
        case_id=case.case_id,
        task=case.task,
        condition=condition,  # type: ignore[arg-type]
        split=case.split,
        probabilities={"label": result.confidence},
        gold=case.gold,
        content_hash=case.content_hash,
        model=result.model,
        provider=result.provider,
        routing_json=routing,
        question_json=messages,
        answer=result.label,
        confidence=result.confidence,
        usage_tokens=_usage_tokens(result.usage),
        latency_ms=latency_ms,
    )


def _chat_pair(condition: str) -> tuple[str, str]:
    if condition == "L3":
        return SONNET_MODEL_ID, SONNET_PROVIDER
    return LUNA_MODEL_ID, LUNA_PROVIDER


def execute_case(
    client: OpenRouterClient,
    case: RunCase,
    condition: str,
    record: Mapping[str, Any],
    *,
    prompts_root: Any = None,
) -> RequestLog:
    """1 ケース 1 条件。失敗は RequestLog.failed に落とさず、呼び出し側が扱う。"""
    bundle = load_bundle(case.task, condition, root=prompts_root)
    started = time.perf_counter()
    try:
        if condition in JEV_CONDITIONS:
            if bundle.state is None or bundle.questions is None:
                raise ValueError(f"{condition} に state/questions が無い")
            state = materialize_state(case.task, bundle.state, record)
            result = client.system_one(state=state, questions=bundle.questions)
            latency_ms = (time.perf_counter() - started) * 1000
            return _from_jev(
                case,
                condition,
                result,
                state=state,
                questions=bundle.questions,
                latency_ms=latency_ms,
            )
        if bundle.llm_messages is None:
            raise ValueError(f"{condition} に llm_messages が無い")
        messages = materialize_messages(case.task, bundle.llm_messages, record)
        model, provider = _chat_pair(condition)
        result = client.chat_completions(
            model=model, messages=messages, provider=provider
        )
        latency_ms = (time.perf_counter() - started) * 1000
        return _from_llm(
            case,
            condition,
            result,
            messages=messages,
            routing=provider_routing(provider),
            latency_ms=latency_ms,
        )
    except (OpenRouterError, ValueError) as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return RequestLog.failed(
            case_id=case.case_id,
            task=case.task,
            condition=condition,  # type: ignore[arg-type]
            split=case.split,
            gold=case.gold,
            content_hash=case.content_hash,
            error=f"{type(exc).__name__}: {exc}",
        )


def execute_for_experiment(
    client: OpenRouterClient,
    records: Mapping[str, Mapping[str, Any]],
    *,
    prompts_root: Any = None,
):
    """`run_experiment` に渡す execute。"""

    def execute(case: RunCase, condition: str) -> RequestLog:
        record = records[case.case_id]
        return execute_case(client, case, condition, record, prompts_root=prompts_root)

    return execute
