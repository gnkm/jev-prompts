# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""H1〜H4 報告に本文キーが残らないこと。"""

from datetime import date
from pathlib import Path

from jev_prompts.report.a_errors import classify_a_error, classify_a_errors
from jev_prompts.report.findings import render_findings, write_findings
from jev_prompts.report.forbidden import FORBIDDEN_TOKENS
from jev_prompts.report.prices import ModelPrice, render_prices
from jev_prompts.runners import published_frame
from test_report import _log


def test_classify_choice_overlap() -> None:
    row = {
        "condition": "A",
        "task": "choice",
        "gold": "transaction_fee_charged",
        "answer": "card_payment_fee_charged",
        "error": None,
    }
    assert classify_a_error(row) == "overlap"
    assert classify_a_error({**row, "answer": "transaction_fee_charged"}) is None


def test_classify_call_failed() -> None:
    row = {
        "condition": "A",
        "task": "noul",
        "gold": "no",
        "answer": None,
        "error": "OpenRouterHttpError: OpenRouter HTTP 429",
    }
    assert classify_a_error(row) == "call_failed"


def test_render_findings_omits_forbidden_tokens(tmp_path: Path) -> None:
    logs = [
        _log(case_id="c0", task="choice", gold="a", answer="a", condition="A"),
        _log(case_id="c0", task="choice", gold="a", answer="b", condition="B1"),
        _log(case_id="c1", task="choice", gold="a", answer="a", condition="A"),
        _log(case_id="c1", task="choice", gold="a", answer="a", condition="B1"),
        _log(
            case_id="c0",
            task="choice",
            gold="a",
            answer="a",
            condition="L1",
            usage_tokens=80,
        ),
    ]
    published = published_frame(logs)
    prices = (
        ModelPrice(
            model_id="typesafe/jev-1.13",
            prompt_per_million=0.042,
            completion_per_million=0.0,
        ),
    )
    text = render_findings(published, prices=prices, measured_on=date(2026, 9, 21))
    for token in FORBIDDEN_TOKENS:
        assert token not in text
    assert "測定日: 2026-09-21" in text
    assert "## H1" in text
    assert "## H4" in text
    path = write_findings(
        published, tmp_path / "findings.md", measured_on=date(2026, 9, 21)
    )
    assert path.is_file()
    errors = classify_a_errors(published)
    assert "state_json" not in errors.columns


def test_render_prices_omits_forbidden_tokens() -> None:
    text = render_prices(
        (
            ModelPrice(
                model_id="openai/gpt-5.6-luna",
                prompt_per_million=0.2,
                completion_per_million=1.2,
            ),
        ),
        measured_on=date(2026, 9, 21),
    )
    for token in FORBIDDEN_TOKENS:
        assert token not in text
    assert "0.2" in text
