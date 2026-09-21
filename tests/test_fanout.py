# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""fan-out は batched と split を別呼び出しにする。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jev_prompts.runners.fanout import FanoutError, agreement, iter_fanout_calls


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
