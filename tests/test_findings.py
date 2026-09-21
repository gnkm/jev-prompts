# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""H1〜H4 報告に本文キーが残らないこと。"""

from datetime import date
from pathlib import Path

import pytest

from jev_prompts.report.a_errors import (
    classify_a_error,
    classify_a_errors,
    read_error_review,
)
from jev_prompts.report.findings import eval_logs, render_findings, write_findings
from jev_prompts.report.forbidden import FORBIDDEN_TOKENS
from jev_prompts.report.prices import ModelPrice, read_prices_markdown, render_prices
from jev_prompts.runners import published_frame
from test_report import HASH_A, _log


def _a_error_logs():
    return published_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="transaction_fee_charged",
                answer="card_payment_fee_charged",
            ),
            _log(
                case_id="c1",
                task="choice",
                gold="transaction_fee_charged",
                answer="card_payment_fee_charged",
            ),
            _log(case_id="n0", task="noul", gold="yes", answer=0.1),
        ]
    )


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
    assert "欠けた課題: score, noul" in text
    assert "- 判定: 判定不能" in text
    path = write_findings(
        published, tmp_path / "findings.md", measured_on=date(2026, 9, 21)
    )
    assert path.is_file()
    errors = classify_a_errors(published)
    assert "state_json" not in errors.columns


def test_eval_logs_keeps_only_test_split() -> None:
    logs = published_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                condition="A",
                split="test",
            ),
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="b",
                condition="A",
                split="dev",
            ),
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="b",
                condition="B1",
                split="test",
            ),
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                condition="B1",
                split="dev",
            ),
        ]
    )
    filtered = eval_logs(logs)
    assert set(filtered["split"].to_list()) == {"test"}
    text = render_findings(logs, measured_on=date(2026, 9, 21))
    assert "choice: top1 A=1.000 B1=0.000" in text


def test_h4_is_undecidable_unless_all_tasks_compare() -> None:
    logs = published_frame(
        [
            _log(case_id="c0", task="choice", gold="a", answer="a", condition="A"),
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                condition="L1",
                usage_tokens=80,
            ),
        ]
    )
    text = render_findings(logs, measured_on=date(2026, 9, 21))
    assert "欠けた課題: score, noul" in text
    assert "3 課題そろわないため判定不能" in text


def test_findings_notes_duplicate_noul_hash() -> None:
    logs = published_frame(
        [
            _log(case_id="noul:1", task="noul", gold="yes", answer=0.9),
            _log(case_id="noul:2", task="noul", gold="no", answer=0.1),
        ]
    )
    assert logs["content_hash"].n_unique() == 1
    assert logs["content_hash"][0] == HASH_A
    text = render_findings(logs, measured_on=date(2026, 9, 21))
    assert "content_hash が一意 1 件" in text
    assert "同一本文の重複" in text


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
    counted = read_error_review(path, _a_error_logs())
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
    with pytest.raises(ValueError, match="本文列"):
        read_error_review(path, _a_error_logs())


def test_read_error_review_requires_a_error_keys(tmp_path: Path) -> None:
    path = tmp_path / "a_error_review.jsonl"
    path.write_text(
        '{"case_id":"c0","task":"choice","mode":"overlap"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="誤答集合"):
        read_error_review(path, _a_error_logs())


def test_read_error_review_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "a_error_review.jsonl"
    path.write_text(
        '{"case_id":"c0","task":"choice","mode":"overlap"}\n'
        '{"case_id":"c0","task":"choice","mode":"literal"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重複"):
        read_error_review(path, _a_error_logs())


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
