# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""fan-out は batched と split を別呼び出しにする。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_prompts.runners.fanout import (
    FanoutCaseResult,
    FanoutError,
    agreement,
    iter_fanout_calls,
    write_fanout_results,
)


def test_iter_fanout_calls_batches_then_splits() -> None:
    questions = {
        "q1": {"type": "noul", "instructions": "one"},
        "q2": {"type": "noul", "instructions": "two"},
    }
    calls = iter_fanout_calls(questions)
    assert [item.mode for item in calls] == ["batched", "split", "split"]
    assert calls[0].questions == questions
    assert calls[1].question_id == "q1"
    assert calls[1].questions == {"q1": questions["q1"]}
    assert calls[2].question_id == "q2"


def test_iter_fanout_calls_rejects_empty() -> None:
    with pytest.raises(FanoutError, match="空"):
        iter_fanout_calls({})


def test_agreement_counts_matching_answers() -> None:
    batched = SimpleNamespace(
        answers={
            "q1": SimpleNamespace(choice="a", score=None, noul=None),
            "q2": SimpleNamespace(choice="b", score=None, noul=None),
        }
    )
    split = {
        "q1": SimpleNamespace(
            answers={"q1": SimpleNamespace(choice="a", score=None, noul=None)}
        ),
        "q2": SimpleNamespace(
            answers={"q2": SimpleNamespace(choice="c", score=None, noul=None)}
        ),
    }
    agreed, compared = agreement(batched, split)
    assert compared == 2
    assert agreed == 1


def test_write_fanout_results_keeps_latency_and_tokens(tmp_path: Path) -> None:
    path = tmp_path / "fanout.jsonl"
    write_fanout_results(
        [
            FanoutCaseResult(
                case_id="choice:c00",
                task="choice",
                batched_ms=10.0,
                split_ms=30.0,
                batched_tokens=40,
                split_tokens=90,
                agreed=1,
                compared=1,
            )
        ],
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert "batched_ms" in text
    assert "split_ms" in text
    assert "batched_tokens" in text
    assert "agreed" in text
