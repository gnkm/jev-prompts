# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""OpenRouter の URL・モデル ID・プロバイダ固定。キーは置かない。"""

from __future__ import annotations

from typing import Final

OPENROUTER_BASE_URL: Final = "https://openrouter.ai/api"
SYSTEMONE_PATH: Final = "/v1/systemone"
CHAT_COMPLETIONS_PATH: Final = "/v1/chat/completions"

JEV_MODEL_ID: Final = "typesafe/jev-1.13"
LUNA_MODEL_ID: Final = "openai/gpt-5.6-luna"
SONNET_MODEL_ID: Final = "anthropic/claude-sonnet-5"

LUNA_PROVIDER: Final = "OpenAI"
SONNET_PROVIDER: Final = "Anthropic"

CHAT_MODELS: Final[dict[str, str]] = {
    LUNA_MODEL_ID: LUNA_PROVIDER,
    SONNET_MODEL_ID: SONNET_PROVIDER,
}

API_KEY_ENV: Final = "OPENROUTER_API_KEY"

PROVIDER_ALLOW_FALLBACKS: Final = False
PROVIDER_REQUIRE_PARAMETERS: Final = True
PROVIDER_DATA_COLLECTION: Final = "deny"

MAIN_TEMPERATURE: Final = 0
MAIN_SEED: Final = 20260921

HTTP_TIMEOUT_SECONDS: Final = 60.0


def provider_routing(order: str) -> dict[str, object]:
    """Chat Completions に必ず付けるプロバイダ固定。"""
    return {
        "order": [order],
        "allow_fallbacks": PROVIDER_ALLOW_FALLBACKS,
        "require_parameters": PROVIDER_REQUIRE_PARAMETERS,
        "data_collection": PROVIDER_DATA_COLLECTION,
    }


def require_chat_pair(model: str, provider: str) -> None:
    """Luna/OpenAI と Sonnet/Anthropic 以外は拒否する。"""
    expected = CHAT_MODELS.get(model)
    if expected is None:
        raise ValueError(f"未許可のモデル: {model}")
    if provider != expected:
        raise ValueError(f"{model} の provider は {expected} に固定")
