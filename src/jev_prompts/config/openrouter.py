# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""OpenRouter の URL・モデル ID・プロバイダ固定。キーは置かない。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

OPENROUTER_BASE_URL: Final = "https://openrouter.ai/api"
SYSTEMONE_PATH: Final = "/v1/systemone"
CHAT_COMPLETIONS_PATH: Final = "/v1/chat/completions"

JEV_MODEL_ID: Final = "typesafe/jev-1.13"
LUNA_MODEL_ID: Final = "openai/gpt-5.6-luna"
SONNET_MODEL_ID: Final = "anthropic/claude-sonnet-5"

LUNA_PROVIDER: Final = "OpenAI"
SONNET_PROVIDER: Final = "Anthropic"
LUNA_PROVIDERS: Final[tuple[str, ...]] = (LUNA_PROVIDER, "Azure")
SONNET_PROVIDERS: Final[tuple[str, ...]] = (SONNET_PROVIDER, "Amazon Bedrock")

CHAT_MODELS: Final[dict[str, tuple[str, ...]]] = {
    LUNA_MODEL_ID: LUNA_PROVIDERS,
    SONNET_MODEL_ID: SONNET_PROVIDERS,
}

API_KEY_ENV: Final = "OPENROUTER_API_KEY"

PROVIDER_ALLOW_FALLBACKS: Final = False
PROVIDER_REQUIRE_PARAMETERS: Final = True
PROVIDER_DATA_COLLECTION: Final = "deny"

MAIN_TEMPERATURE: Final = 0
MAIN_SEED: Final = 20260921

HTTP_TIMEOUT_SECONDS: Final = 60.0
CONTEXT_WINDOW_TOKENS: Final = 32_000
DETERMINISM_SAMPLE_SIZE: Final = 10
NONDETERMINISTIC_REPEATS: Final = 3


def _provider_names(order: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(order, str):
        names = (order,)
    else:
        names = tuple(order)
    if not names:
        raise ValueError("provider が空")
    return names


def provider_routing(order: str | Sequence[str]) -> dict[str, object]:
    """Chat Completions に必ず付けるプロバイダ固定。"""
    return {
        "order": list(_provider_names(order)),
        "allow_fallbacks": PROVIDER_ALLOW_FALLBACKS,
        "require_parameters": PROVIDER_REQUIRE_PARAMETERS,
        "data_collection": PROVIDER_DATA_COLLECTION,
    }


def require_chat_pair(model: str, provider: str | Sequence[str]) -> None:
    """許可したモデルと、そのモデルの provider.order 以外は拒否する。"""
    allowed = CHAT_MODELS.get(model)
    if allowed is None:
        raise ValueError(f"未許可のモデル: {model}")
    extra = [name for name in _provider_names(provider) if name not in allowed]
    if extra:
        raise ValueError(f"{model} の provider は {list(allowed)} に固定")
