# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""決定性・トークン上限・モデル版の事前確認。失敗したら本ランに進まない。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jev_prompts.clients import MissingApiKeyError, OpenRouterClient
from jev_prompts.config import (
    API_KEY_ENV,
    CONTEXT_WINDOW_TOKENS,
    DETERMINISM_SAMPLE_SIZE,
    JEV_MODEL_ID,
    NONDETERMINISTIC_REPEATS,
)
from jev_prompts.prompts.catalog import load_bundle
from jev_prompts.runners.experiment import RunCase
from jev_prompts.runners.payload import load_run_cases, require_bodies

type ExecuteFn = Callable[[RunCase, str, dict[str, Any]], Any]


class PreflightError(ValueError):
    """事前確認に失敗した。本ランに進まない。"""


@dataclass(frozen=True, slots=True)
class TokenCheck:
    task: str
    condition: str
    tokens: int
    limit: int

    @property
    def ok(self) -> bool:
        return self.tokens <= self.limit


@dataclass(frozen=True, slots=True)
class PreflightReport:
    bodies: int
    model: str
    token_checks: tuple[TokenCheck, ...]
    deterministic: bool
    repeats: int


def require_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingApiKeyError(
            f"{API_KEY_ENV} が未設定。キーは環境変数または secret のみ"
        )
    return key


def estimate_tokens(payload: object) -> int:
    """UTF-8 を約 4 バイト/トークンで見積もる。ライブラリは足さない。"""
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    size = len(text.encode("utf-8"))
    return max(1, (size + 3) // 4)


def _dummy_record(task: str) -> dict[str, Any]:
    if task == "choice":
        return {"text": "preflight query"}
    if task == "noul":
        return {"message": "preflight message"}
    return {
        "query": "preflight query",
        "title": "preflight title",
        "description": "preflight description",
    }


def check_token_limits(
    *,
    root: Path | None = None,
    limit: int = CONTEXT_WINDOW_TOKENS,
) -> tuple[TokenCheck, ...]:
    """条件 C と Choice の A（77 選択肢）がコンテキストを超えないこと。"""
    from jev_prompts.runners.payload import request_payload

    targets = (("choice", "A"), ("choice", "C"), ("score", "C"), ("noul", "C"))
    checks: list[TokenCheck] = []
    overflow: list[str] = []
    for task, condition in targets:
        bundle = load_bundle(task, condition, root=root)
        payload = request_payload(bundle, _dummy_record(task))
        tokens = estimate_tokens(payload)
        check = TokenCheck(task=task, condition=condition, tokens=tokens, limit=limit)
        checks.append(check)
        if not check.ok:
            overflow.append(f"{task}/{condition}={tokens}")
    if overflow:
        raise PreflightError(f"トークン上限 {limit} を超える: {', '.join(overflow)}")
    return tuple(checks)


def probe_model_version(client: OpenRouterClient) -> str:
    """System One を 1 回呼び、応答の model（パッチ付き）を記録する。"""
    result = client.system_one(
        state="preflight",
        questions={
            "probe": {
                "type": "noul",
                "instructions": "preflight probe",
                "criteria": {"true": "yes", "false": "no"},
            }
        },
    )
    model = result.model
    if not model.startswith(JEV_MODEL_ID):
        raise PreflightError(f"モデルが {JEV_MODEL_ID} 系ではない: {model}")
    return model


def _execution_error(value: Any) -> str | None:
    err = getattr(value, "error", None)
    if isinstance(err, str) and err:
        return err
    return None


def _answer_key(value: Any) -> str:
    if hasattr(value, "answers"):
        raw = {
            qid: {
                "choice": getattr(ans, "choice", None),
                "score": getattr(ans, "score", None),
                "noul": getattr(ans, "noul", None),
                "label": getattr(ans, "label", None),
            }
            for qid, ans in value.answers.items()
        }
        return json.dumps(raw, sort_keys=True, default=str)
    if hasattr(value, "label"):
        return json.dumps(
            {"label": value.label, "confidence": value.confidence},
            sort_keys=True,
            default=str,
        )
    if hasattr(value, "answer"):
        return json.dumps(value.answer, sort_keys=True, default=str)
    return json.dumps(value, sort_keys=True, default=str)


def check_determinism(
    cases: Sequence[tuple[RunCase, dict[str, Any]]],
    execute: ExecuteFn,
    *,
    sample_size: int = DETERMINISM_SAMPLE_SIZE,
) -> bool:
    """同一入力を 2 回実行し、出力が一致するか。失敗ログは決定的と見ない。"""
    sample = list(cases[:sample_size])
    if not sample:
        raise PreflightError("決定性確認のケースが無い")
    first = [execute(case, "A", record) for case, record in sample]
    second = [execute(case, "A", record) for case, record in sample]
    failures = [
        msg for item in (*first, *second) if (msg := _execution_error(item)) is not None
    ]
    if failures:
        raise PreflightError(f"決定性確認の呼び出しが失敗した: {failures[0]}")
    return all(
        _answer_key(left) == _answer_key(right)
        for left, right in zip(first, second, strict=True)
    )


def write_preflight_report(report: PreflightReport, path: Path) -> None:
    """本ランが repeats を読めるよう、判定をローカルログへ残す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "bodies": report.bodies,
        "model": report.model,
        "deterministic": report.deterministic,
        "repeats": report.repeats,
        "token_checks": [
            {
                "task": item.task,
                "condition": item.condition,
                "tokens": item.tokens,
                "limit": item.limit,
            }
            for item in report.token_checks
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_repeats(path: Path) -> int:
    """preflight.json が無ければ 1 回。"""
    if not path.is_file():
        return 1
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        repeats = int(raw["repeats"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PreflightError(f"preflight 判定が読めない: {path}") from exc
    if repeats < 1:
        raise PreflightError("repeats は 1 以上")
    return repeats


def run_preflight(
    raw_root: Path,
    cases_root: Path,
    *,
    client: OpenRouterClient | None = None,
    execute: ExecuteFn | None = None,
    prompts_root: Path | None = None,
    sample_size: int = DETERMINISM_SAMPLE_SIZE,
) -> PreflightReport:
    """キー・本文・トークン・モデル版・決定性を順に確認する。"""
    require_api_key()
    bodies = require_bodies(raw_root, cases_root)
    token_checks = check_token_limits(root=prompts_root)
    owned_client = client is None
    active = client or OpenRouterClient()
    try:
        model = probe_model_version(active)
        cases = load_run_cases(raw_root, cases_root)
        if execute is None:
            from jev_prompts.runners.execute import execute_case

            def _execute(case: RunCase, condition: str, record: dict[str, Any]) -> Any:
                return execute_case(active, case, condition, record)

            bound = _execute
        else:
            bound = execute
        deterministic = check_determinism(cases, bound, sample_size=sample_size)
    finally:
        if owned_client:
            active.close()
    repeats = 1 if deterministic else NONDETERMINISTIC_REPEATS
    return PreflightReport(
        bodies=bodies,
        model=model,
        token_checks=token_checks,
        deterministic=deterministic,
        repeats=repeats,
    )
