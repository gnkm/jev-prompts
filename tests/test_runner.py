# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""ランナーはケースネスト。公開行に本文キーは無く、probabilities は必須。"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from jev_prompts.data.schema import BODY_COLUMNS
from jev_prompts.prompts import CONDITIONS
from jev_prompts.runners import (
    PUBLISHED_COLUMNS,
    REQUEST_LOG_COLUMNS,
    LogSchemaError,
    RequestLog,
    RunCase,
    iter_case_conditions,
    local_frame,
    run_experiment,
    to_published,
    write_local_logs,
    write_published_records,
)
from jev_prompts.runners.execute import _usage_tokens, repeating_execute
from jev_prompts.runners.experiment import assert_resume_matches

REPO_ROOT = Path(__file__).resolve().parents[1]
HASH_A = "a" * 64
HASH_B = "b" * 64

CASES = (
    RunCase(
        case_id="choice:c00",
        task="choice",
        split="test",
        gold="ham",
        content_hash=HASH_A,
    ),
    RunCase(
        case_id="choice:c01",
        task="choice",
        split="test",
        gold="spam",
        content_hash=HASH_B,
    ),
)


def _log(case: RunCase, condition: str, **overrides: object) -> RequestLog:
    row: dict[str, object] = {
        "case_id": case.case_id,
        "task": case.task,
        "condition": condition,
        "split": case.split,
        "probabilities": {"ham": 0.8, "spam": 0.2},
        "gold": case.gold,
        "content_hash": case.content_hash,
        "model": "typesafe/jev-1.13",
        "provider": None,
        "state_json": {"text": f"body-{case.case_id}"},
        "question_json": {"intent": {"type": "choice"}},
        "answer": "ham",
        "confidence": 0.8,
        "usage_tokens": 12,
        "latency_ms": 3.5,
        "routing_json": {"allow_fallbacks": False},
        "request_id": "req-1",
    }
    row.update(overrides)
    return RequestLog(**row)  # type: ignore[arg-type]


def test_run_order_is_case_nested_not_condition_nested() -> None:
    calls: list[tuple[str, str]] = []

    def execute(case: RunCase, condition: str) -> RequestLog:
        calls.append((case.case_id, condition))
        return _log(case, condition)

    local, published = run_experiment(CASES, execute, conditions=CONDITIONS)
    case_ids = [case.case_id for case in CASES]
    case_nested = [(cid, cond) for cid in case_ids for cond in CONDITIONS]
    condition_nested = [(cid, cond) for cond in CONDITIONS for cid in case_ids]

    assert calls == case_nested
    assert calls != condition_nested
    assert local.height == len(CASES) * len(CONDITIONS)
    assert published.height == local.height
    assert local["case_id"].to_list() == [cid for cid, _ in case_nested]
    assert local["condition"].to_list() == [cond for _, cond in case_nested]


def test_iter_case_conditions_is_not_condition_outer() -> None:
    pairs = list(iter_case_conditions(CASES, ("A", "B1")))
    assert [(c.case_id, cond) for c, cond in pairs] == [
        ("choice:c00", "A"),
        ("choice:c00", "B1"),
        ("choice:c01", "A"),
        ("choice:c01", "B1"),
    ]


def test_one_request_one_row() -> None:
    def execute(case: RunCase, condition: str) -> RequestLog:
        return _log(case, condition)

    local, _published = run_experiment(CASES, execute, conditions=("A", "C"))
    assert local.height == 4
    keys = list(
        zip(local["case_id"].to_list(), local["condition"].to_list(), strict=True)
    )
    assert len(keys) == len(set(keys))


def test_local_log_keeps_state_json_published_does_not() -> None:
    def execute(case: RunCase, condition: str) -> RequestLog:
        return _log(case, condition)

    local, published = run_experiment(CASES[:1], execute, conditions=("A",))
    assert "state_json" in local.columns
    assert "question_json" in local.columns
    parsed = json.loads(local["state_json"][0])
    assert parsed["text"] == "body-choice:c00"
    assert "state_json" not in published.columns
    assert "question_json" not in published.columns
    assert not (set(published.columns) & BODY_COLUMNS)
    assert "content_hash" in published.columns
    assert "probabilities" in published.columns


@pytest.mark.parametrize("body_col", sorted(BODY_COLUMNS))
def test_published_record_rejects_body_keys(body_col: str) -> None:
    def execute(case: RunCase, condition: str) -> RequestLog:
        return _log(case, condition)

    _local, published = run_experiment(CASES[:1], execute, conditions=("A",))
    dirty = published.with_columns(pl.lit("secret").alias(body_col))
    with pytest.raises(LogSchemaError, match="本文フィールド"):
        write_published_records(dirty, Path("unused.jsonl"))


def test_to_published_drops_body_and_keeps_probabilities(tmp_path: Path) -> None:
    def execute(case: RunCase, condition: str) -> RequestLog:
        return _log(case, condition)

    local, _published = run_experiment(CASES[:1], execute, conditions=("A",))
    published = to_published(local)
    assert set(published.columns) == set(PUBLISHED_COLUMNS)
    assert "state_json" in set(REQUEST_LOG_COLUMNS)
    assert "state_json" not in set(PUBLISHED_COLUMNS)
    probs = json.loads(published["probabilities"][0])
    assert probs == {"ham": 0.8, "spam": 0.2}

    local_path = tmp_path / "local.jsonl"
    pub_path = tmp_path / "published.jsonl"
    write_local_logs(local, local_path)
    write_published_records(published, pub_path)
    local_text = local_path.read_text(encoding="utf-8")
    pub_text = pub_path.read_text(encoding="utf-8")
    assert "state_json" in local_text
    assert "body-choice:c00" in local_text
    assert "state_json" not in pub_text
    assert "body-choice:c00" not in pub_text
    assert "probabilities" in pub_text


def _sample_frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    def execute(case: RunCase, condition: str) -> RequestLog:
        return _log(case, condition)

    return run_experiment(CASES[:1], execute, conditions=("A",))


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("not-json", "JSON ではない"),
        ("[0.8, 0.2]", "オブジェクト"),
        ('{"ham": "high"}', "数値ではない"),
        ('{"ham": true}', "数値ではない"),
        ("null", "必須"),
        ("1", "オブジェクト"),
    ],
)
def test_write_rejects_invalid_probabilities(
    tmp_path: Path, raw: str, match: str
) -> None:
    local, published = _sample_frames()
    dirty_local = local.with_columns(pl.lit(raw).alias("probabilities"))
    dirty_published = published.with_columns(pl.lit(raw).alias("probabilities"))
    with pytest.raises(LogSchemaError, match=match):
        write_local_logs(dirty_local, tmp_path / "local.jsonl")
    with pytest.raises(LogSchemaError, match=match):
        write_published_records(dirty_published, tmp_path / "published.jsonl")
    assert not (tmp_path / "local.jsonl").exists()
    assert not (tmp_path / "published.jsonl").exists()


def test_write_accepts_numeric_probability_object(tmp_path: Path) -> None:
    local, published = _sample_frames()
    write_local_logs(local, tmp_path / "local.jsonl")
    write_published_records(published, tmp_path / "published.jsonl")
    assert (tmp_path / "local.jsonl").is_file()
    assert (tmp_path / "published.jsonl").is_file()


def test_probabilities_required() -> None:
    case = CASES[0]
    with pytest.raises(TypeError):
        RequestLog(
            case_id=case.case_id,
            task=case.task,
            condition="A",
            split=case.split,
            gold=case.gold,
            content_hash=case.content_hash,
        )
    with pytest.raises(LogSchemaError, match="probabilities"):
        RequestLog(
            case_id=case.case_id,
            task=case.task,
            condition="A",
            split=case.split,
            gold=case.gold,
            content_hash=case.content_hash,
            probabilities=None,  # type: ignore[arg-type]
        )


def test_assert_resume_matches_accepts_same_cases() -> None:
    existing = local_frame([_log(CASES[0], "A")])
    assert_resume_matches(existing, CASES[:1])


def test_assert_resume_matches_rejects_extra_case_id() -> None:
    existing = local_frame([_log(CASES[0], "A"), _log(CASES[1], "A")])
    with pytest.raises(LogSchemaError, match="今回のケースが無い"):
        assert_resume_matches(existing, CASES[:1])


def test_assert_resume_matches_rejects_split_mismatch() -> None:
    existing = local_frame([_log(CASES[0], "A")])
    other = RunCase(
        case_id=CASES[0].case_id,
        task=CASES[0].task,
        split="dev",
        gold=CASES[0].gold,
        content_hash=CASES[0].content_hash,
    )
    with pytest.raises(LogSchemaError, match="split"):
        assert_resume_matches(existing, [other])


def test_assert_resume_matches_rejects_hash_mismatch() -> None:
    existing = local_frame([_log(CASES[0], "A")])
    other = RunCase(
        case_id=CASES[0].case_id,
        task=CASES[0].task,
        split=CASES[0].split,
        gold=CASES[0].gold,
        content_hash=HASH_B,
    )
    with pytest.raises(LogSchemaError, match="content_hash"):
        assert_resume_matches(existing, [other])


def test_assert_resume_matches_accepts_patched_model() -> None:
    existing = local_frame([_log(CASES[0], "A", model="typesafe/jev-1.13-20260917")])
    assert_resume_matches(existing, CASES[:1])


def test_assert_resume_matches_rejects_model_mismatch() -> None:
    existing = local_frame([_log(CASES[0], "A", model="openai/gpt-5.6-luna")])
    with pytest.raises(LogSchemaError, match="model"):
        assert_resume_matches(existing, CASES[:1])


def test_run_experiment_skips_completed_pairs() -> None:
    calls: list[tuple[str, str]] = []

    def execute(case: RunCase, condition: str) -> RequestLog:
        calls.append((case.case_id, condition))
        return _log(case, condition)

    local, _published = run_experiment(
        CASES[:1],
        execute,
        conditions=("A", "B1"),
        skip={(CASES[0].case_id, "A")},
    )
    assert calls == [(CASES[0].case_id, "B1")]
    assert local.height == 1
    assert local["condition"].to_list() == ["B1"]


def test_execute_exception_becomes_error_row_with_probabilities() -> None:
    def execute(case: RunCase, condition: str) -> RequestLog:
        raise RuntimeError("boom")

    local, published = run_experiment(CASES[:1], execute, conditions=("A",))
    assert local.height == 1
    assert "boom" in local["error"][0]
    assert json.loads(local["probabilities"][0]) == {}
    assert published["error"][0] == local["error"][0]
    assert "state_json" not in published.columns


def test_logs_are_polars_frames() -> None:
    def execute(case: RunCase, condition: str) -> RequestLog:
        return _log(case, condition)

    local, published = run_experiment(CASES[:1], execute, conditions=("A",))
    assert isinstance(local, pl.DataFrame)
    assert isinstance(published, pl.DataFrame)


def test_gitignore_excludes_local_logs() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/logs/" in gitignore


def test_readme_describes_case_nested_runner() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "ケースごとに全条件" in readme
    assert "PublishedRecord" in readme
    assert "data/logs/" in readme


def test_repeating_execute_averages_numeric_answers() -> None:
    case = CASES[0]
    seen = {"n": 0}

    def execute(_case: RunCase, _condition: str) -> RequestLog:
        seen["n"] += 1
        score = float(seen["n"])
        return _log(_case, _condition, answer=score, confidence=score / 10)

    wrapped = repeating_execute(execute, repeats=3)
    log = wrapped(case, "A")
    assert seen["n"] == 3
    assert log.answer == pytest.approx(2.0)
    assert log.confidence == pytest.approx(0.2)
    assert log.usage_tokens == 36
    assert log.routing_json is not None
    assert log.routing_json["repeats"] == 3


def test_usage_tokens_reads_input_output_keys() -> None:
    assert _usage_tokens({"input_tokens": 10, "output_tokens": 2}) == 12
    assert _usage_tokens({"prompt_tokens": 3, "completion_tokens": 4}) == 7
    assert _usage_tokens({"total_tokens": 9, "input_tokens": 1}) == 9
    assert _usage_tokens({}) is None
