# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""測定日のモデル単価。公開物に本文キーは書かない。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from jev_prompts.clients import MissingApiKeyError
from jev_prompts.config import (
    API_KEY_ENV,
    JEV_MODEL_ID,
    LUNA_MODEL_ID,
    OPENROUTER_BASE_URL,
    SONNET_MODEL_ID,
)
from jev_prompts.config.openrouter import HTTP_TIMEOUT_SECONDS
from jev_prompts.report.forbidden import reject_forbidden_text

MEASURED_MODELS = (JEV_MODEL_ID, LUNA_MODEL_ID, SONNET_MODEL_ID)
_MODELS_PATH = "/v1/models"


@dataclass(frozen=True, slots=True)
class ModelPrice:
    model_id: str
    prompt_per_million: float | None
    completion_per_million: float | None


def _auth_headers() -> dict[str, str]:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingApiKeyError(
            f"{API_KEY_ENV} が未設定。キーは環境変数または secret のみ"
        )
    return {"Authorization": f"Bearer {key}"}


def _per_million(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value * 1_000_000


def _index_models(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        if isinstance(ident, str) and ident:
            out[ident] = item
    return out


def fetch_model_catalog(http: httpx.Client) -> dict[str, dict[str, Any]]:
    """チャット系と decisions 系を足して ID で引ける表にする。"""
    headers = _auth_headers()
    chat = http.get(f"{OPENROUTER_BASE_URL}{_MODELS_PATH}", headers=headers)
    chat.raise_for_status()
    catalog = _index_models(chat.json())
    decisions = http.get(
        f"{OPENROUTER_BASE_URL}{_MODELS_PATH}",
        headers=headers,
        params={"output_modalities": "decisions"},
    )
    decisions.raise_for_status()
    catalog.update(_index_models(decisions.json()))
    return catalog


def prices_from_catalog(
    catalog: Mapping[str, Mapping[str, Any]],
) -> tuple[ModelPrice, ...]:
    rows: list[ModelPrice] = []
    for model_id in MEASURED_MODELS:
        item = catalog.get(model_id) or {}
        pricing = item.get("pricing") if isinstance(item, Mapping) else None
        if not isinstance(pricing, Mapping):
            pricing = {}
        rows.append(
            ModelPrice(
                model_id=model_id,
                prompt_per_million=_per_million(pricing.get("prompt")),
                completion_per_million=_per_million(pricing.get("completion")),
            )
        )
    return tuple(rows)


def fetch_prices(*, timeout: float = HTTP_TIMEOUT_SECONDS) -> tuple[ModelPrice, ...]:
    """OpenRouter の掲載単価を取る。キーが無ければ失敗する。"""
    transport = httpx.HTTPTransport(retries=0)
    with httpx.Client(timeout=timeout, transport=transport) as http:
        return prices_from_catalog(fetch_model_catalog(http))


def render_prices(prices: tuple[ModelPrice, ...], *, measured_on: date) -> str:
    """markdown。本文キーは出さない。"""
    lines = [
        "# 測定単価",
        "",
        f"測定日: {measured_on.isoformat()}",
        "",
        "単位は 1M トークンあたり USD（入力 / 出力）。OpenRouter 掲載値。",
        "",
        "| モデル | 入力 | 出力 |",
        "| --- | --- | --- |",
    ]
    for row in prices:
        if row.prompt_per_million is None:
            prompt = ""
        else:
            prompt = f"{row.prompt_per_million:.6g}"
        completion = (
            ""
            if row.completion_per_million is None
            else f"{row.completion_per_million:.6g}"
        )
        lines.append(f"| `{row.model_id}` | {prompt} | {completion} |")
    lines.append("")
    return "\n".join(lines)


def write_prices(
    dest: Path, prices: tuple[ModelPrice, ...], *, measured_on: date
) -> Path:
    text = render_prices(prices, measured_on=measured_on)
    reject_forbidden_text(text, source="prices.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest
