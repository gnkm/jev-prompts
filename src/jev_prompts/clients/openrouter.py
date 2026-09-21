# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""OpenRouter への HTTP 1 本。Jev は systemone、LLM は chat。再試行しない。"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Self

import httpx

from jev_prompts.config.openrouter import (
    API_KEY_ENV,
    CHAT_COMPLETIONS_PATH,
    HTTP_TIMEOUT_SECONDS,
    JEV_MODEL_ID,
    MAIN_SEED,
    MAIN_TEMPERATURE,
    OPENROUTER_BASE_URL,
    SYSTEMONE_PATH,
    provider_routing,
)

type QuestionType = Literal["choice", "score", "noul"]


class OpenRouterError(Exception):
    """OpenRouter 呼び出しの失敗。再試行しない。"""


class MissingApiKeyError(OpenRouterError):
    """API キーが環境変数に無い。"""


class OpenRouterHttpError(OpenRouterError):
    """HTTP エラー。呼び出し側が不正解にする。"""

    def __init__(self, message: str, *, status_code: int, body: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class OpenRouterParseError(OpenRouterError):
    """応答のパース失敗。呼び出し側が不正解にする。"""


@dataclass(frozen=True, slots=True)
class JevAnswer:
    type: QuestionType
    choice: str | None = None
    score: float | None = None
    noul: float | None = None
    confidence: float | None = None
    probabilities: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class JevResult:
    model: str
    provider: str | None
    answers: tuple[JevAnswer, ...]
    usage: dict[str, Any] | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LlmResult:
    model: str
    provider: str | None
    label: str
    confidence: float
    content: str
    usage: dict[str, Any] | None
    raw: dict[str, Any]


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingApiKeyError(
            f"{API_KEY_ENV} が未設定。キーは環境変数または secret のみ"
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _as_object(value: Any, *, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OpenRouterParseError(f"{what} がオブジェクトではない")
    return value


def _as_list(value: Any, *, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise OpenRouterParseError(f"{what} が配列ではない")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OpenRouterParseError(f"文字列ではない: {type(value).__name__}")
    return value


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise OpenRouterParseError("usage がオブジェクトではない")
    return value


def _require_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OpenRouterParseError(f"{field} が数値ではない")
    return float(value)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
            else:
                raise OpenRouterParseError("Chat Completions の content が解釈できない")
        return "".join(parts)
    raise OpenRouterParseError("Chat Completions の content が文字列ではない")


def _parse_jev_answer(raw: Any) -> JevAnswer:
    obj = _as_object(raw, what="answer")
    qtype = obj.get("type")
    if qtype not in {"choice", "score", "noul"}:
        raise OpenRouterParseError(f"未知の answer.type: {qtype!r}")
    confidence: float | None = None
    if "confidence" in obj and obj["confidence"] is not None:
        confidence = _require_number(obj["confidence"], field="confidence")
    probabilities: dict[str, float] | None = None
    if "probabilities" in obj and obj["probabilities"] is not None:
        probs = _as_object(obj["probabilities"], what="probabilities")
        probabilities = {
            str(key): _require_number(val, field=f"probabilities.{key}")
            for key, val in probs.items()
        }
    if qtype == "choice":
        choice = obj.get("choice")
        if not isinstance(choice, str) or not choice:
            raise OpenRouterParseError("choice の answer.choice が無い")
        return JevAnswer(
            type="choice",
            choice=choice,
            confidence=confidence,
            probabilities=probabilities,
        )
    if qtype == "score":
        if "score" not in obj:
            raise OpenRouterParseError("score の answer.score が無い")
        return JevAnswer(
            type="score",
            score=_require_number(obj["score"], field="score"),
            confidence=confidence,
            probabilities=probabilities,
        )
    if "noul" not in obj:
        raise OpenRouterParseError("noul の answer.noul が無い")
    return JevAnswer(
        type="noul",
        noul=_require_number(obj["noul"], field="noul"),
        confidence=confidence,
        probabilities=probabilities,
    )


def _parse_jev_result(data: dict[str, Any]) -> JevResult:
    answers_raw = _as_list(data.get("answers"), what="answers")
    if not answers_raw:
        raise OpenRouterParseError("answers が空")
    answers = tuple(_parse_jev_answer(item) for item in answers_raw)
    model = data.get("model")
    if not isinstance(model, str) or not model:
        raise OpenRouterParseError("応答の model が無い")
    return JevResult(
        model=model,
        provider=_optional_str(data.get("provider")),
        answers=answers,
        usage=_optional_mapping(data.get("usage")),
        raw=data,
    )


def _parse_llm_result(data: dict[str, Any]) -> LlmResult:
    choices = _as_list(data.get("choices"), what="choices")
    if not choices:
        raise OpenRouterParseError("choices が空")
    first = _as_object(choices[0], what="choices[0]")
    message = _as_object(first.get("message"), what="choices[0].message")
    content = _message_text(message.get("content")).strip()
    if not content:
        raise OpenRouterParseError("Chat Completions の content が空")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as err:
        raise OpenRouterParseError("LLM 出力が JSON ではない") from err
    obj = _as_object(parsed, what="LLM JSON")
    label = obj.get("label")
    if not isinstance(label, str) or not label:
        raise OpenRouterParseError("LLM JSON の label が無い")
    if "confidence" not in obj:
        raise OpenRouterParseError("LLM JSON の confidence が無い")
    confidence = _require_number(obj["confidence"], field="confidence")
    model = data.get("model")
    if not isinstance(model, str) or not model:
        raise OpenRouterParseError("応答の model が無い")
    return LlmResult(
        model=model,
        provider=_optional_str(data.get("provider")),
        label=label,
        confidence=confidence,
        content=content,
        usage=_optional_mapping(data.get("usage")),
        raw=data,
    )


class OpenRouterClient:
    """1 クライアント・2 エンドポイント。失敗しても再試行しない。"""

    def __init__(
        self,
        *,
        http: httpx.Client | None = None,
        timeout: float = HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self._timeout = timeout
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=0),
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def system_one(
        self,
        *,
        state: str | Mapping[str, Any],
        questions: Sequence[Mapping[str, Any]],
    ) -> JevResult:
        if not questions:
            raise ValueError("questions が空")
        payload = {
            "model": JEV_MODEL_ID,
            "state": dict(state) if isinstance(state, Mapping) else state,
            "questions": [dict(item) for item in questions],
        }
        data = self._post_json(SYSTEMONE_PATH, payload)
        return _parse_jev_result(data)

    def chat_completions(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        provider: str,
        temperature: float | None = MAIN_TEMPERATURE,
        seed: int | None = MAIN_SEED,
        response_format: Mapping[str, Any] | None = None,
    ) -> LlmResult:
        if model == JEV_MODEL_ID or model.startswith("typesafe/jev"):
            raise ValueError("Jev は Chat Completions では呼べない")
        if not messages:
            raise ValueError("messages が空")
        if not provider:
            raise ValueError("provider が空")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [dict(item) for item in messages],
            "provider": provider_routing(provider),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if seed is not None:
            payload["seed"] = seed
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        data = self._post_json(CHAT_COMPLETIONS_PATH, payload)
        return _parse_llm_result(data)

    def _post_json(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        url = f"{OPENROUTER_BASE_URL}{path}"
        try:
            response = self._http.post(
                url,
                json=dict(payload),
                headers=_headers(),
                timeout=self._timeout,
            )
        except httpx.RequestError as err:
            raise OpenRouterHttpError(
                f"OpenRouter への接続に失敗: {err}",
                status_code=0,
                body="",
            ) from err
        body = response.text
        if response.status_code >= 400:
            raise OpenRouterHttpError(
                f"OpenRouter HTTP {response.status_code}",
                status_code=response.status_code,
                body=body,
            )
        try:
            data = response.json()
        except json.JSONDecodeError as err:
            raise OpenRouterParseError("応答が JSON ではない") from err
        obj = _as_object(data, what="応答")
        if obj.get("error"):
            raise OpenRouterHttpError(
                "OpenRouter が error を返した",
                status_code=response.status_code,
                body=body,
            )
        return obj
