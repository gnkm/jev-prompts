# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""プロンプトカタログ: ファイルを読み、A から 1 軸だけ変える。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from jev_prompts.config import PROMPTS_DIR
from jev_prompts.data.schema import TASKS
from jev_prompts.prompts import (
    CONDITIONS,
    JEV_CONDITIONS,
    CatalogError,
    load_all,
    load_bundle,
    sole_question,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_SRC = REPO_ROOT / "src" / "jev_prompts" / "prompts"


def _file_payload(task: str, condition: str) -> dict[str, object]:
    bundle = load_bundle(task, condition)
    return json.loads(bundle.source_path.read_text(encoding="utf-8"))


def test_prompts_dir_is_repo_catalog() -> None:
    assert PROMPTS_DIR == REPO_ROOT / "prompts"
    assert (PROMPTS_DIR / "README.md").is_file()


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("condition", CONDITIONS)
def test_every_condition_is_a_file(task: str, condition: str) -> None:
    bundle = load_bundle(task, condition)
    assert bundle.source_path.is_file()
    assert bundle.source_path.is_relative_to(PROMPTS_DIR)
    raw = _file_payload(task, condition)
    assert raw["task"] == task
    assert raw["condition"] == condition
    assert bundle.questions == raw.get("questions")
    assert bundle.state == raw.get("state")
    assert bundle.llm_messages == raw.get("llm_messages")


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("condition", JEV_CONDITIONS)
def test_jev_fixture_has_one_question(task: str, condition: str) -> None:
    question = sole_question(load_bundle(task, condition))
    assert question["type"] == task


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("condition", ["B1", "B2", "B3"])
def test_question_conditions_keep_a_state(task: str, condition: str) -> None:
    baseline = load_bundle(task, "A")
    other = load_bundle(task, condition)
    assert other.state == baseline.state
    assert other.questions != baseline.questions


@pytest.mark.parametrize("task", TASKS)
def test_b2_same_instructions_different_criteria(task: str) -> None:
    baseline = sole_question(load_bundle(task, "A"))
    b2 = sole_question(load_bundle(task, "B2"))
    assert b2["instructions"] == baseline["instructions"]
    assert b2["criteria"] != baseline["criteria"]


@pytest.mark.parametrize("task", TASKS)
def test_c_same_questions_extra_state_keys(task: str) -> None:
    baseline = load_bundle(task, "A")
    noisy = load_bundle(task, "C")
    assert noisy.questions == baseline.questions
    assert baseline.state is not None
    assert noisy.state is not None
    assert set(baseline.state) < set(noisy.state)
    for key, value in baseline.state.items():
        assert noisy.state[key] == value


@pytest.mark.parametrize("task", TASKS)
def test_b3_same_criteria_different_instructions(task: str) -> None:
    baseline = sole_question(load_bundle(task, "A"))
    b3 = sole_question(load_bundle(task, "B3"))
    assert b3["criteria"] == baseline["criteria"]
    assert b3["instructions"] != baseline["instructions"]


@pytest.mark.parametrize("task", TASKS)
def test_l3_messages_match_l2(task: str) -> None:
    assert load_bundle(task, "L3").llm_messages == load_bundle(task, "L2").llm_messages


def test_missing_catalog_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="カタログが無い"):
        load_bundle("choice", "A", root=tmp_path)


def test_loader_does_not_fill_missing_questions(tmp_path: Path) -> None:
    path = tmp_path / "choice"
    path.mkdir()
    (path / "C.json").write_text(
        json.dumps(
            {
                "task": "choice",
                "condition": "C",
                "state": {"query": "", "noise": True},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="questions"):
        load_bundle("choice", "C", root=tmp_path)


def test_catalog_strings_live_in_files_not_python() -> None:
    needles: list[str] = []
    for task in TASKS:
        raw = _file_payload(task, "A")
        questions = raw["questions"]
        assert isinstance(questions, dict)
        question = next(iter(questions.values()))
        assert isinstance(question, dict)
        instructions = question["instructions"]
        assert isinstance(instructions, str)
        needles.append(instructions)

    py_source: list[str] = []
    for path in sorted(PROMPTS_SRC.glob("*.py")):
        py_source.append(path.read_text(encoding="utf-8"))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for needle in needles:
                    assert needle not in node.value

    joined = "\n".join(py_source)
    for needle in needles:
        assert needle not in joined
        found = False
        for path in PROMPTS_DIR.rglob("*.json"):
            if needle in path.read_text(encoding="utf-8"):
                found = True
                break
        assert found, needle


def test_load_all_covers_three_tasks_and_eight_conditions() -> None:
    bundles = load_all()
    assert len(bundles) == len(TASKS) * len(CONDITIONS)
    assert {(b.task, b.condition) for b in bundles} == {
        (task, condition) for task in TASKS for condition in CONDITIONS
    }


BANKING77_LABELS: tuple[str, ...] = (
    "card_arrival",
    "card_linking",
    "exchange_rate",
    "card_payment_wrong_exchange_rate",
    "extra_charge_on_statement",
    "pending_cash_withdrawal",
    "fiat_currency_support",
    "card_delivery_estimate",
    "automatic_top_up",
    "card_not_working",
    "exchange_via_app",
    "lost_or_stolen_card",
    "age_limit",
    "pin_blocked",
    "contactless_not_working",
    "top_up_by_bank_transfer_charge",
    "pending_top_up",
    "cancel_transfer",
    "top_up_limits",
    "wrong_amount_of_cash_received",
    "card_payment_fee_charged",
    "transfer_not_received_by_recipient",
    "supported_cards_and_currencies",
    "getting_virtual_card",
    "card_acceptance",
    "top_up_reverted",
    "balance_not_updated_after_cheque_or_cash_deposit",
    "card_payment_not_recognised",
    "edit_personal_details",
    "why_verify_identity",
    "unable_to_verify_identity",
    "get_physical_card",
    "visa_or_mastercard",
    "topping_up_by_card",
    "disposable_card_limits",
    "compromised_card",
    "atm_support",
    "direct_debit_payment_not_recognised",
    "passcode_forgotten",
    "declined_cash_withdrawal",
    "pending_card_payment",
    "lost_or_stolen_phone",
    "request_refund",
    "declined_transfer",
    "Refund_not_showing_up",
    "declined_card_payment",
    "pending_transfer",
    "terminate_account",
    "card_swallowed",
    "transaction_charged_twice",
    "verify_source_of_funds",
    "transfer_timing",
    "reverted_card_payment?",
    "change_pin",
    "beneficiary_not_allowed",
    "transfer_fee_charged",
    "receiving_money",
    "failed_transfer",
    "transfer_into_account",
    "verify_top_up",
    "getting_spare_card",
    "top_up_by_cash_or_cheque",
    "order_physical_card",
    "virtual_card_not_working",
    "wrong_exchange_rate_for_cash_withdrawal",
    "get_disposable_virtual_card",
    "top_up_failed",
    "balance_not_updated_after_bank_transfer",
    "cash_withdrawal_not_recognised",
    "exchange_charge",
    "top_up_by_card_charge",
    "activate_my_card",
    "cash_withdrawal_charge",
    "card_about_to_expire",
    "apple_pay_or_google_pay",
    "verify_my_identity",
    "country_support",
)


def test_choice_a_has_banking77_plus_other() -> None:
    criteria = sole_question(load_bundle("choice", "A"))["criteria"]
    assert set(criteria) == {*BANKING77_LABELS, "other"}
    structured = criteria["card_payment_fee_charged"]
    assert isinstance(structured, dict)
    assert "what" in structured
    assert "not_for" in structured
    assert "examples" in structured
    assert criteria["other"] == {"what": "None of the intents above"}


@pytest.mark.parametrize("condition", ["B1", "B2"])
def test_choice_question_conditions_keep_77_without_other(condition: str) -> None:
    criteria = sole_question(load_bundle("choice", condition))["criteria"]
    assert set(criteria) == set(BANKING77_LABELS)
    assert "other" not in criteria


def test_choice_b2_fee_intents_share_description() -> None:
    criteria = sole_question(load_bundle("choice", "B2"))["criteria"]
    for label in (
        "card_payment_fee_charged",
        "cash_withdrawal_charge",
        "transfer_fee_charged",
    ):
        assert criteria[label] == "Fees and charges"


def test_choice_c_state_is_large() -> None:
    noisy = load_bundle("choice", "C").state
    assert noisy is not None
    assert len(json.dumps(noisy)) >= 6000
    assert len(str(noisy["terms_of_service"])) >= 4000


def test_creation_times_are_recorded_minutes() -> None:
    path = PROMPTS_DIR / "creation_time.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["unit"] == "minutes"
    for task in TASKS:
        for condition in ("A", "L2"):
            minutes = raw[task][condition]
            assert isinstance(minutes, int)
            assert minutes >= 1


@pytest.mark.parametrize("condition", ["L1", "L2"])
def test_choice_llm_lists_all_intents(condition: str) -> None:
    messages = load_bundle("choice", condition).llm_messages
    assert messages is not None
    joined = "\n".join(str(item.get("content", "")) for item in messages)
    for label in BANKING77_LABELS:
        assert label in joined


@pytest.mark.parametrize("task", TASKS)
def test_l2_has_schema_and_three_examples(task: str) -> None:
    messages = load_bundle(task, "L2").llm_messages
    assert messages is not None
    joined = "\n".join(str(item.get("content", "")) for item in messages)
    assert '"label"' in joined
    assert '"confidence"' in joined
    assert joined.count("->") >= 3
