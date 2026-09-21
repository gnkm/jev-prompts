# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""H1〜H4 報告に本文キーが残らないこと。"""

from datetime import date
from pathlib import Path

from jev_prompts.report.a_errors import (
    classify_a_error,
    classify_a_errors,
    read_error_review,
)
from jev_prompts.report.findings import render_findings, write_findings
from jev_prompts.report.forbidden import FORBIDDEN_TOKENS
from jev_prompts.report.prices import ModelPrice, read_prices_markdown, render_prices
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
    assert "## 測定単価" in text
    assert "0.042" in text
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


def test_read_error_review_counts_modes(tmp_path: Path) -> None:
    path = tmp_path / "a_error_review.jsonl"
    path.write_text(
        '{"case_id":"c0","task":"choice","mode":"overlap"}\n'
        '{"case_id":"c1","task":"choice","mode":"overlap"}\n'
        '{"case_id":"n0","task":"noul","mode":"literal"}\n',
        encoding="utf-8",
    )
    counted = read_error_review(path)
    assert counted.columns == ["task", "mode", "n"]
    rows = {(r["task"], r["mode"]): r["n"] for r in counted.to_dicts()}
    assert rows[("choice", "overlap")] == 2
    assert rows[("noul", "literal")] == 1


def test_read_error_review_rejects_body_columns(tmp_path: Path) -> None:
    path = tmp_path / "a_error_review.jsonl"
    path.write_text(
        '{"case_id":"c0","task":"choice","mode":"overlap","body":"nope"}\n',
        encoding="utf-8",
    )
    try:
        read_error_review(path)
    except ValueError as exc:
        assert "本文列" in str(exc)
    else:
        raise AssertionError("本文列を含む目視分類を受け入れた")


def test_read_prices_markdown_roundtrip(tmp_path: Path) -> None:
    prices = (
        ModelPrice(
            model_id="typesafe/jev-1.13",
            prompt_per_million=0.042,
            completion_per_million=0.0,
        ),
    )
    text = render_prices(prices, measured_on=date(2026, 9, 21))
    path = tmp_path / "prices.md"
    path.write_text(text, encoding="utf-8")
    loaded = read_prices_markdown(path)
    assert loaded == prices
