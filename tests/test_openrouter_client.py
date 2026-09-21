# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""OpenRouter クライアント。HTTP はモックし、実ネットに出ない。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from jev_prompts.clients import (
    MissingApiKeyError,
    OpenRouterClient,
    OpenRouterHttpError,
    OpenRouterParseError,
)
from jev_prompts.config import (
    API_KEY_ENV,
    CHAT_COMPLETIONS_PATH,
    JEV_MODEL_ID,
    LUNA_MODEL_ID,
    LUNA_PROVIDER,
    OPENROUTER_BASE_URL,
    SONNET_MODEL_ID,
    SONNET_PROVIDER,
    SYSTEMONE_PATH,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

SYSTEMONE_URL = f"{OPENROUTER_BASE_URL}{SYSTEMONE_PATH}"
CHAT_URL = f"{OPENROUTER_BASE_URL}{CHAT_COMPLETIONS_PATH}"

CHOICE_QUESTION = {
    "type": "choice",
    "instructions": "Pick one.",
    "criteria": "labels: ham, spam",
}
CHOICE_ANSWER = {
    "type": "choice",
    "choice": "ham",
    "confidence": 0.8,
    "probabilities": {"ham": 0.8, "spam": 0.2},
}


def _json_response(payload: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str = "test-key",
) -> tuple[OpenRouterClient, list[httpx.Request]]:
    monkeypatch.setenv(API_KEY_ENV, api_key)
    captured: list[httpx.Request] = []

    def wrap(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrap))
    return OpenRouterClient(http=http), captured


def test_system_one_posts_systemone_not_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": [CHOICE_ANSWER],
            }
        )

    client, captured = _client(monkeypatch, handler)
    result = client.system_one(state="hello", questions=[CHOICE_QUESTION])
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == SYSTEMONE_URL
    assert "chat/completions" not in str(request.url)
    body = json.loads(request.content.decode())
    assert body["model"] == JEV_MODEL_ID
    assert result.answers[0].choice == "ham"
    assert request.headers["Authorization"] == "Bearer test-key"


def test_chat_completions_pins_luna_and_sonnet_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        return _json_response(
            {
                "model": body["model"],
                "provider": body["provider"]["order"][0],
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"label": "ham", "confidence": 0.5})
                        }
                    }
                ],
            }
        )

    client, captured = _client(monkeypatch, handler)
    luna = client.chat_completions(
        model=LUNA_MODEL_ID,
        messages=[{"role": "user", "content": "hi"}],
        provider=LUNA_PROVIDER,
    )
    sonnet = client.chat_completions(
        model=SONNET_MODEL_ID,
        messages=[{"role": "user", "content": "hi"}],
        provider=SONNET_PROVIDER,
    )
    assert [str(req.url) for req in captured] == [CHAT_URL, CHAT_URL]
    luna_body = json.loads(captured[0].content.decode())
    sonnet_body = json.loads(captured[1].content.decode())
    assert luna_body["model"] == LUNA_MODEL_ID
    assert luna_body["provider"] == {
        "order": [LUNA_PROVIDER],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
    }
    assert sonnet_body["model"] == SONNET_MODEL_ID
    assert sonnet_body["provider"]["order"] == [SONNET_PROVIDER]
    assert luna.label == "ham"
    assert sonnet.confidence == 0.5


def test_parse_failure_raises_and_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"model": "typesafe/jev-1.13-20260917", "answers": []})

    client, captured = _client(monkeypatch, handler)
    with pytest.raises(OpenRouterParseError, match="answers"):
        client.system_one(state="hello", questions=[CHOICE_QUESTION])
    assert len(captured) == 1


def test_llm_invalid_json_raises_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "model": LUNA_MODEL_ID,
                "choices": [{"message": {"content": "not-json"}}],
            }
        )

    client, captured = _client(monkeypatch, handler)
    with pytest.raises(OpenRouterParseError, match="JSON"):
        client.chat_completions(
            model=LUNA_MODEL_ID,
            messages=[{"role": "user", "content": "hi"}],
            provider=LUNA_PROVIDER,
        )
    assert len(captured) == 1


def test_http_error_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    client, captured = _client(monkeypatch, handler)
    with pytest.raises(OpenRouterHttpError) as exc:
        client.system_one(state="hello", questions=[CHOICE_QUESTION])
    assert exc.value.status_code == 500
    assert len(captured) == 1


def test_missing_api_key_raises_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response({"answers": [CHOICE_ANSWER], "model": JEV_MODEL_ID})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenRouterClient(http=http)
    with pytest.raises(MissingApiKeyError, match=API_KEY_ENV):
        client.system_one(state="hello", questions=[CHOICE_QUESTION])
    assert captured == []


def test_jev_model_rejected_on_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Jev を Chat Completions に送ってはいけない")

    client, captured = _client(monkeypatch, handler)
    with pytest.raises(ValueError, match="Chat Completions"):
        client.chat_completions(
            model=JEV_MODEL_ID,
            messages=[{"role": "user", "content": "hi"}],
            provider=LUNA_PROVIDER,
        )
    assert captured == []


def test_source_has_no_hardcoded_api_keys() -> None:
    forbidden = ("sk-or-", "OPENROUTER_API_KEY=")
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} にキーらしい文字列がある"


def test_readme_documents_endpoints_and_model_ids() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/api/v1/systemone" in text
    assert "/api/v1/chat/completions" in text
    assert JEV_MODEL_ID in text
    assert LUNA_MODEL_ID in text
    assert SONNET_MODEL_ID in text
    assert API_KEY_ENV in text
