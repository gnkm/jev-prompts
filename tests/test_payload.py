# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""カタログの空欄にケース本文を載せる。"""

from jev_prompts.runners.payload import materialize_messages, materialize_state


def test_choice_state_fills_query_and_keeps_noise_keys() -> None:
    state = materialize_state(
        "choice",
        {"query": "", "terms_of_service": "noise"},
        {"text": "Where is my card?"},
    )
    assert state["query"] == "Where is my card?"
    assert state["terms_of_service"] == "noise"


def test_score_state_fills_product() -> None:
    state = materialize_state(
        "score",
        {"query": "", "product": {"title": "", "description": ""}},
        {"query": "shoes", "title": "Trail", "description": "red"},
    )
    assert state["query"] == "shoes"
    assert state["product"]["title"] == "Trail"
    assert state["product"]["description"] == "red"


def test_noul_messages_replace_placeholder() -> None:
    messages = materialize_messages(
        "noul",
        [{"role": "user", "content": "Message: {{message}}"}],
        {"message": "WIN now"},
    )
    assert messages[0]["content"] == "Message: WIN now"
