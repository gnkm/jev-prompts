# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""fan-out は本ランと別ファイル。まとめ 1 回 vs 分割 n 回をモックで比べる。"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import polars as pl
import pytest

from jev_prompts.runners import (
    EVAL_LOG_FILENAME,
    FANOUT_BATCHED_LOG_FILENAME,
    FANOUT_SPLIT_LOG_FILENAME,
    LogSchemaError,
    RequestLog,
    RunCase,
    compare_fanout,
    drop_fanout_rows,
    eval_log_path,
    fanout_log_paths,
    is_fanout_row,
    read_local_logs,
    run_experiment,
    run_fanout_pair,
    split_questions,
    write_local_logs,
)

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

QUESTIONS = {
    "intent": {"type": "choice", "instructions": "intent?"},
    "dept": {"type": "choice", "instructions": "dept?"},
}


def _log(
    case: RunCase,
    questions: Mapping[str, Mapping[str, object]],
    *,
    tokens: int,
    latency_ms: float,
    answer_prefix: str = "ans",
) -> RequestLog:
    qids = list(questions)
    if len(qids) == 1:
        answer: str | object = f"{answer_prefix}-{qids[0]}"
    else:
        answer = {qid: f"{answer_prefix}-{qid}" for qid in qids}
    return RequestLog(
        case_id=case.case_id,
        task=case.task,
        condition="A",
        split=case.split,
        probabilities={"ham": 0.7, "spam": 0.3},
        gold=case.gold,
        content_hash=case.content_hash,
        model="typesafe/jev-1.13",
        question_json=dict(questions),
        answer=answer if isinstance(answer, str) else json.dumps(answer),
        usage_tokens=tokens,
        latency_ms=latency_ms,
        routing_json={"allow_fallbacks": False},
    )


def _execute(
    case: RunCase, questions: Mapping[str, Mapping[str, object]]
) -> RequestLog:
    n = len(questions)
    tokens = 10 if n > 1 else 8
    latency = 5.0 if n > 1 else 4.0
    return _log(case, questions, tokens=tokens, latency_ms=latency)


def test_log_filenames_keep_fanout_off_eval() -> None:
    directory = Path("/tmp/logs")
    batched, split = fanout_log_paths(directory)
    eval_path = eval_log_path(directory)
    assert batched != split
    assert batched != eval_path
    assert split != eval_path
    assert batched.name == FANOUT_BATCHED_LOG_FILENAME
    assert split.name == FANOUT_SPLIT_LOG_FILENAME
    assert eval_path.name == EVAL_LOG_FILENAME


def test_split_questions_is_one_id_per_slice() -> None:
    slices = split_questions(QUESTIONS)
    assert len(slices) == 2
    assert slices[0] == {"intent": QUESTIONS["intent"]}
    assert slices[1] == {"dept": QUESTIONS["dept"]}
    with pytest.raises(LogSchemaError, match="空"):
        split_questions({})


def test_mock_two_paths_write_separate_files(tmp_path: Path) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(
        case: RunCase, questions: Mapping[str, Mapping[str, object]]
    ) -> RequestLog:
        calls.append((case.case_id, tuple(questions)))
        return _execute(case, questions)

    batched, split, _comparison, batched_path, split_path = run_fanout_pair(
        CASES, QUESTIONS, execute, log_dir=tmp_path
    )
    assert batched_path is not None and split_path is not None
    assert {batched_path.name, split_path.name} == {
        FANOUT_BATCHED_LOG_FILENAME,
        FANOUT_SPLIT_LOG_FILENAME,
    }
    assert not (tmp_path / EVAL_LOG_FILENAME).exists()
    assert read_local_logs(batched_path).height == batched.height == len(CASES)
    assert (
        read_local_logs(split_path).height
        == split.height
        == (len(CASES) * len(QUESTIONS))
    )
    case_ids = [case.case_id for case in CASES]
    assert calls == [
        *((cid, ("intent", "dept")) for cid in case_ids),
        *((cid, (qid,)) for cid in case_ids for qid in QUESTIONS),
    ]


def test_mock_fanout_compares_cost_latency_and_match(tmp_path: Path) -> None:
    _batched, _split, comparison, batched_path, split_path = run_fanout_pair(
        CASES, QUESTIONS, _execute, log_dir=tmp_path
    )
    assert batched_path != split_path
    assert (
        comparison.batched_requests,
        comparison.split_requests,
        comparison.batched_usage_tokens,
        comparison.split_usage_tokens,
    ) == (2, 4, 20, 32)
    assert comparison.batched_latency_ms == pytest.approx(10.0)
    assert comparison.split_latency_ms == pytest.approx(16.0)
    assert (comparison.compared, comparison.matched) == (4, 4)
    assert comparison.match_rate == pytest.approx(1.0)


def test_eval_aggregation_drops_mixed_fanout_rows(tmp_path: Path) -> None:
    def eval_execute(case: RunCase, condition: str) -> RequestLog:
        return RequestLog(
            case_id=case.case_id,
            task=case.task,
            condition=condition,
            split=case.split,
            probabilities={"ham": 1.0},
            gold=case.gold,
            content_hash=case.content_hash,
            answer="ham",
            usage_tokens=3,
            routing_json={"allow_fallbacks": False},
        )

    eval_local, _published = run_experiment(
        CASES[:1], eval_execute, conditions=("A", "B1")
    )
    eval_path = eval_log_path(tmp_path)
    write_local_logs(eval_local, eval_path)

    _batched, _split, _cmp, batched_path, split_path = run_fanout_pair(
        CASES[:1], QUESTIONS, _execute, log_dir=tmp_path
    )
    assert batched_path is not None
    assert split_path is not None
    assert eval_path != batched_path
    assert eval_path != split_path

    eval_from_disk = read_local_logs(eval_path)
    batched_from_disk = read_local_logs(batched_path)
    split_from_disk = read_local_logs(split_path)
    assert eval_from_disk.height == 2
    assert all(not is_fanout_row(raw) for raw in eval_from_disk["routing_json"])
    assert all(is_fanout_row(raw) for raw in batched_from_disk["routing_json"])
    assert all(is_fanout_row(raw) for raw in split_from_disk["routing_json"])

    mixed = pl.concat(
        [eval_from_disk, batched_from_disk, split_from_disk],
        how="vertical",
    )
    cleaned = drop_fanout_rows(mixed)
    assert cleaned.height == eval_from_disk.height
    assert cleaned["condition"].to_list() == eval_from_disk["condition"].to_list()
    assert cleaned["usage_tokens"].sum() == 6
    assert mixed.height == eval_from_disk.height + batched_from_disk.height + (
        split_from_disk.height
    )


def test_compare_fanout_is_not_accuracy(tmp_path: Path) -> None:
    def execute(
        case: RunCase, questions: Mapping[str, Mapping[str, object]]
    ) -> RequestLog:
        prefix = "batch" if len(questions) > 1 else "split"
        n = len(questions)
        return _log(
            case,
            questions,
            tokens=10 if n > 1 else 8,
            latency_ms=5.0 if n > 1 else 4.0,
            answer_prefix=prefix,
        )

    batched, split, comparison, _b, _s = run_fanout_pair(
        CASES[:1], QUESTIONS, execute, log_dir=tmp_path
    )
    again = compare_fanout(batched, split, n_questions=2)
    assert again == comparison
    assert comparison.matched == 0
    assert comparison.compared == 2
    assert comparison.match_rate == pytest.approx(0.0)
    assert "accuracy" not in comparison.__dataclass_fields__


def test_execute_exception_stamps_fanout_path() -> None:
    def execute(
        case: RunCase, questions: Mapping[str, Mapping[str, object]]
    ) -> RequestLog:
        raise RuntimeError("boom")

    batched, split, comparison, _b, _s = run_fanout_pair(CASES[:1], QUESTIONS, execute)
    assert "boom" in batched["error"][0]
    assert all(is_fanout_row(raw) for raw in batched["routing_json"])
    assert all(is_fanout_row(raw) for raw in split["routing_json"])
    assert comparison.compared == 2
    assert comparison.matched == 0
    assert comparison.match_rate == pytest.approx(0.0)
    assert comparison.split_requests == 2


def test_missing_split_answer_is_not_full_match() -> None:
    def execute(
        case: RunCase, questions: Mapping[str, Mapping[str, object]]
    ) -> RequestLog:
        if len(questions) == 1 and "dept" in questions:
            raise RuntimeError("dept missing")
        return _execute(case, questions)

    _batched, _split, comparison, _b, _s = run_fanout_pair(
        CASES[:1], QUESTIONS, execute
    )
    assert comparison.compared == 2
    assert comparison.matched == 1
    assert comparison.match_rate == pytest.approx(0.5)


def test_architecture_describes_separate_fanout_run() -> None:
    text = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "投機的 fan-out" in text
    assert "fanout-batched.jsonl" in text
    assert "fanout-split.jsonl" in text
    assert "精度比較" in text


def test_mock_cli_writes_two_log_files(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(REPO_ROOT / "scripts" / "run_fanout.py"),
            "--mock",
            "--log-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    batched = tmp_path / FANOUT_BATCHED_LOG_FILENAME
    split = tmp_path / FANOUT_SPLIT_LOG_FILENAME
    assert batched.is_file()
    assert split.is_file()
    assert batched != split
    assert not (tmp_path / EVAL_LOG_FILENAME).exists()
    assert "batched:" in result.stdout
    assert "split:" in result.stdout
