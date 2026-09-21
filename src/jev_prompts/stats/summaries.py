# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""対応サンプル上の指標。独立 2 標本の要約は置かない。"""

from __future__ import annotations

from collections.abc import Sequence


def mean_binary(values: Sequence[object]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    return sum(1.0 if bool(v) else 0.0 for v in values) / n


def mean_abs_error(pairs: Sequence[object]) -> float | None:
    errors: list[float] = []
    for item in pairs:
        pred, gold = item  # type: ignore[misc]
        if pred is None or gold is None:
            continue
        errors.append(abs(float(pred) - float(gold)))
    if not errors:
        return None
    return sum(errors) / len(errors)


def mean_optional(values: Sequence[object]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def pairwise_auc(pairs: Sequence[object]) -> float | None:
    """P(pos > neg) + 0.5 P(tie)。クラスが片方しか無いときは None。"""
    pos: list[float] = []
    neg: list[float] = []
    for item in pairs:
        pred, gold_yes = item  # type: ignore[misc]
        if pred is None or gold_yes is None:
            continue
        (pos if gold_yes else neg).append(float(pred))
    if not pos or not neg:
        return None
    total = 0.0
    count = 0
    for p in pos:
        for n in neg:
            if p > n:
                total += 1.0
            elif p == n:
                total += 0.5
            count += 1
    return total / count
