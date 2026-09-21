# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""パス・モデル名・閾値。秘匿情報は置かない。"""

from jev_prompts.config.openrouter import (
    API_KEY_ENV,
    CHAT_COMPLETIONS_PATH,
    JEV_MODEL_ID,
    LUNA_MODEL_ID,
    LUNA_PROVIDER,
    OPENROUTER_BASE_URL,
    SONNET_MODEL_ID,
    SONNET_PROVIDER,
    SYSTEMONE_PATH,
    provider_routing,
)

__all__ = [
    "API_KEY_ENV",
    "CHAT_COMPLETIONS_PATH",
    "JEV_MODEL_ID",
    "LUNA_MODEL_ID",
    "LUNA_PROVIDER",
    "OPENROUTER_BASE_URL",
    "SONNET_MODEL_ID",
    "SONNET_PROVIDER",
    "SYSTEMONE_PATH",
    "provider_routing",
]
