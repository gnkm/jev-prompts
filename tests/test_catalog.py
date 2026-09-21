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
