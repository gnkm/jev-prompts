# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""ケースと条件を OpenRouter 呼び出しに載せる。再試行しない。"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
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
    LUNA_PROVIDERS,
    MAIN_SEED,
    SONNET_MODEL_ID,
    SONNET_PROVIDERS,
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


def _chat_route(condition: str) -> tuple[str, tuple[str, ...], int | None]:
    if condition == "L3":
        return SONNET_MODEL_ID, SONNET_PROVIDERS, None
    return LUNA_MODEL_ID, LUNA_PROVIDERS, MAIN_SEED


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
        model, providers, seed = _chat_route(condition)
        result = client.chat_completions(
            model=model, messages=messages, provider=providers, seed=seed
        )
        latency_ms = (time.perf_counter() - started) * 1000
        return _from_llm(
            case,
            condition,
            result,
            messages=messages,
            routing=provider_routing(providers),
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


def _scalar_answer(answer: JevAnswer) -> str | float | None:
    if answer.choice is not None:
        return answer.choice
    if answer.score is not None:
        return answer.score
    return answer.noul


def _fanout_answer(result: JevResult) -> str | float | None:
    items = list(result.answers.items())
    if len(items) == 1:
        return _scalar_answer(items[0][1])
    return json.dumps(
        {qid: _scalar_answer(item) for qid, item in items},
        ensure_ascii=False,
    )


def execute_for_fanout(
    client: OpenRouterClient,
    records: Mapping[str, Mapping[str, Any]],
    *,
    prompts_root: Any = None,
):
    """`run_fanout_pair` に渡す execute。質問スライスをそのまま送る。"""

    def execute(
        case: RunCase, questions: Mapping[str, Mapping[str, Any]]
    ) -> RequestLog:
        record = records[case.case_id]
        bundle = load_bundle(case.task, "A", root=prompts_root)
        packed = {str(qid): dict(item) for qid, item in questions.items()}
        started = time.perf_counter()
        try:
            if bundle.state is None:
                raise ValueError(f"{case.task}/A に state が無い")
            state = materialize_state(case.task, bundle.state, record)
            result = client.system_one(state=state, questions=packed)
            latency_ms = (time.perf_counter() - started) * 1000
            primary = _primary_answer(result)
            return RequestLog(
                case_id=case.case_id,
                task=case.task,
                condition="A",
                split=case.split,
                probabilities=_probabilities(primary),
                gold=case.gold,
                content_hash=case.content_hash,
                model=result.model,
                provider=result.provider,
                state_json=state,
                question_json=packed,
                answer=_fanout_answer(result),
                confidence=primary.confidence,
                usage_tokens=_usage_tokens(result.usage),
                latency_ms=latency_ms,
            )
        except (OpenRouterError, ValueError) as exc:
            return RequestLog.failed(
                case_id=case.case_id,
                task=case.task,
                condition="A",
                split=case.split,
                gold=case.gold,
                content_hash=case.content_hash,
                error=f"{type(exc).__name__}: {exc}",
                question_json=packed,
            )

    return execute


def average_request_logs(logs: Sequence[RequestLog]) -> RequestLog:
    """非決定時の複数回実行を 1 行に平均する。失敗があれば失敗のまま返す。"""
    if not logs:
        raise ValueError("平均するログが無い")
    failed = [log for log in logs if log.error]
    if failed:
        return failed[0]
    first = logs[0]
    n = len(logs)
    keys: set[str] = set()
    for log in logs:
        keys.update(log.probabilities)
    probabilities = {
        key: sum(log.probabilities.get(key, 0.0) for log in logs) / n for key in keys
    }
    answers = [log.answer for log in logs]
    if all(
        isinstance(item, int | float) and not isinstance(item, bool) for item in answers
    ):
        answer: str | float | None = sum(float(item) for item in answers) / n
    else:
        strings = [item for item in answers if isinstance(item, str)]
        answer = Counter(strings).most_common(1)[0][0] if strings else first.answer

    def mean(attr: str) -> float | None:
        values = [
            getattr(log, attr)
            for log in logs
            if isinstance(getattr(log, attr), int | float)
            and not isinstance(getattr(log, attr), bool)
        ]
        if not values:
            return None
        return sum(values) / len(values)

    usage_tokens = _sum_usage_tokens(logs)
    routing = (
        dict(first.routing_json) if isinstance(first.routing_json, Mapping) else {}
    )
    routing["repeats"] = n
    return RequestLog(
        case_id=first.case_id,
        task=first.task,
        condition=first.condition,
        split=first.split,
        probabilities=probabilities,
        gold=first.gold,
        content_hash=first.content_hash,
        model=first.model,
        provider=first.provider,
        request_id=first.request_id,
        routing_json=routing,
        state_json=first.state_json,
        question_json=first.question_json,
        answer=answer,
        confidence=mean("confidence"),
        usage_tokens=usage_tokens,
        latency_ms=mean("latency_ms"),
    )


def _sum_usage_tokens(logs: Sequence[RequestLog]) -> int | None:
    """コスト用。欠損があれば合計しない。精度用の平均とは分ける。"""
    total = 0
    for log in logs:
        tokens = log.usage_tokens
        if tokens is None or isinstance(tokens, bool) or not isinstance(tokens, int):
            return None
        total += tokens
    return total


def repeating_execute(
    execute: Callable[[RunCase, str], RequestLog], repeats: int
) -> Callable[[RunCase, str], RequestLog]:
    """repeats 回実行して平均した execute を返す。"""
    if repeats < 1:
        raise ValueError("repeats は 1 以上")
    if repeats == 1:
        return execute

    def wrapped(case: RunCase, condition: str) -> RequestLog:
        logs = [execute(case, condition) for _ in range(repeats)]
        return average_request_logs(logs)

    return wrapped
