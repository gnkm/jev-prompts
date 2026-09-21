# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""A の誤答を失敗モードに振る。本文は見ない。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

import polars as pl

from jev_prompts.data.pools import CHOICE_BOUNDARY_LABELS, SCORE_BOUNDARY_LABELS
from jev_prompts.data.schema import SCORE_GOLD

ERROR_MODES = (
    "literal",
    "overlap",
    "thin_input",
    "label_noise",
    "call_failed",
)
MODE_LABELS = {
    "literal": "字義どおり",
    "overlap": "選択肢の重なり",
    "thin_input": "入力の不足",
    "label_noise": "gold のノイズ",
    "call_failed": "呼び出し失敗",
}


def classify_a_error(row: Mapping[str, Any]) -> str | None:
    """A の誤答 1 件。正解は None。"""
    if str(row.get("condition") or "") != "A":
        return None
    if row.get("error"):
        return "call_failed"
    task = str(row.get("task") or "")
    gold = row.get("gold")
    answer = row.get("answer")
    if _is_correct(task, gold, answer):
        return None
    if task == "choice":
        if str(gold) in CHOICE_BOUNDARY_LABELS or str(answer) in CHOICE_BOUNDARY_LABELS:
            return "overlap"
        return "literal"
    if task == "score":
        return _score_mode(gold, answer)
    return _noul_mode(gold, answer)


def classify_a_errors(logs: pl.DataFrame) -> pl.DataFrame:
    """task × 失敗モードの件数。入力本文は列に出さない。"""
    schema = {"task": pl.String, "mode": pl.String, "n": pl.UInt32}
    if logs.height == 0 or "condition" not in logs.columns:
        return pl.DataFrame(schema=schema)
    counts: Counter[tuple[str, str]] = Counter()
    for row in logs.filter(pl.col("condition") == "A").to_dicts():
        mode = classify_a_error(row)
        if mode is None:
            continue
        counts[(str(row["task"]), mode)] += 1
    if not counts:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(
        [
            {"task": task, "mode": mode, "n": n}
            for (task, mode), n in sorted(counts.items())
        ]
    )


def _is_correct(task: str, gold: Any, answer: Any) -> bool:
    if task == "choice":
        return str(answer) == str(gold)
    if task == "score":
        mapped = _score_gold(gold)
        if mapped is None:
            return False
        try:
            return round(float(answer)) == mapped
        except (TypeError, ValueError):
            return False
    try:
        pred = float(answer)
    except (TypeError, ValueError):
        return False
    gold_yes = str(gold) in {"yes", "spam"}
    return (pred >= 0.5) == gold_yes


def _score_gold(gold: Any) -> int | None:
    if str(gold) in SCORE_GOLD:
        return SCORE_GOLD[str(gold)]
    try:
        return int(gold)
    except (TypeError, ValueError):
        return None


def _score_mode(gold: Any, answer: Any) -> str:
    mapped = _score_gold(gold)
    if mapped is None:
        return "label_noise"
    try:
        pred = round(float(answer))
    except (TypeError, ValueError):
        return "thin_input"
    pair = {pred, mapped}
    if pair <= {1, 2} or str(gold) in SCORE_BOUNDARY_LABELS:
        return "overlap"
    if abs(pred - mapped) >= 2:
        return "literal"
    return "thin_input"


def _noul_mode(gold: Any, answer: Any) -> str:
    gold_yes = str(gold) in {"yes", "spam"}
    try:
        pred_yes = float(answer) >= 0.5
    except (TypeError, ValueError):
        return "thin_input"
    if (not gold_yes) and pred_yes:
        return "overlap"
    return "literal"
