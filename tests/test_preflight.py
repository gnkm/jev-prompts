# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""事前確認: トークン上限・決定性・キー。ライブ API は叩かない。"""

from __future__ import annotations

from pathlib import Path

import pytest

from jev_prompts.clients import MissingApiKeyError
from jev_prompts.config import CONTEXT_WINDOW_TOKENS, JEV_MODEL_ID
from jev_prompts.runners.experiment import RunCase
from jev_prompts.runners.preflight import (
    PreflightError,
    PreflightReport,
    check_determinism,
    check_token_limits,
    estimate_tokens,
    read_repeats,
    require_api_key,
    write_preflight_report,
)
from jev_prompts.runners.schema import RequestLog


def test_estimate_tokens_rounds_up() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 5) == 2


def test_choice_a_and_condition_c_fit_context_window() -> None:
    checks = check_token_limits()
    names = {(item.task, item.condition) for item in checks}
    assert ("choice", "A") in names
    assert ("choice", "C") in names
    for item in checks:
        assert item.ok
        assert item.tokens <= CONTEXT_WINDOW_TOKENS


def test_token_limit_failure() -> None:
    with pytest.raises(PreflightError, match="トークン上限"):
        check_token_limits(limit=1)


def test_require_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError, match="OPENROUTER_API_KEY"):
        require_api_key()


def test_require_api_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "  secret  ")
    assert require_api_key() == "secret"


def test_determinism_match() -> None:
    case = RunCase(
        case_id="choice:c00",
        task="choice",
        split="dev",
        gold="x",
        content_hash="a" * 64,
    )

    def execute(_case: RunCase, _condition: str, _record: dict) -> str:
        return "same"

    assert check_determinism([(case, {})], execute, sample_size=1) is True


def test_determinism_mismatch() -> None:
    case = RunCase(
        case_id="choice:c00",
        task="choice",
        split="dev",
        gold="x",
        content_hash="a" * 64,
    )
    seen = {"n": 0}

    def execute(_case: RunCase, _condition: str, _record: dict) -> int:
        seen["n"] += 1
        return seen["n"]

    assert check_determinism([(case, {})], execute, sample_size=1) is False


def test_help_model_id_constant() -> None:
    assert JEV_MODEL_ID == "typesafe/jev-1.13"


def test_determinism_failed_logs_are_not_deterministic() -> None:
    case = RunCase(
        case_id="choice:c00",
        task="choice",
        split="dev",
        gold="x",
        content_hash="a" * 64,
    )
    log = RequestLog.failed(
        case_id=case.case_id,
        task=case.task,
        condition="A",
        split=case.split,
        gold=case.gold,
        content_hash=case.content_hash,
        error="OpenRouterHttpError: boom",
    )

    def execute(_case: RunCase, _condition: str, _record: dict) -> RequestLog:
        return log

    with pytest.raises(PreflightError, match="呼び出しが失敗した"):
        check_determinism([(case, {})], execute, sample_size=1)


def test_write_and_read_repeats(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    report = PreflightReport(
        bodies=3,
        model="typesafe/jev-1.13-20260917",
        token_checks=(),
        deterministic=False,
        repeats=3,
        case_ids=("choice:c00",),
    )
    write_preflight_report(report, path)
    assert read_repeats(path, case_ids=("choice:c00",)) == 3
    with pytest.raises(PreflightError, match="無い"):
        read_repeats(tmp_path / "missing.json")
    with pytest.raises(PreflightError, match="ケース"):
        read_repeats(path, case_ids=("choice:other",))


def test_read_repeats_rejects_unrelated_model(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    path.write_text(
        '{"repeats": 3, "model": "openai/gpt-5.6-luna", "case_ids": ["c"]}\n',
        encoding="utf-8",
    )
    with pytest.raises(PreflightError, match="モデル"):
        read_repeats(path)
