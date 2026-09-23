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


def expected_calibration_error(
    pairs: Sequence[object], *, n_bins: int = 10
) -> float | None:
    """較正の確率と正誤の ECE。空ビンは重み 0。"""
    scored: list[tuple[float, float]] = []
    for item in pairs:
        prob, correct = item  # type: ignore[misc]
        if prob is None or correct is None:
            continue
        scored.append((float(prob), 1.0 if bool(correct) else 0.0))
    if not scored:
        return None
    last = n_bins - 1
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for prob, yes in scored:
        idx = int(prob * n_bins)
        if idx < 0:
            idx = 0
        elif idx > last:
            idx = last
        bins[idx].append((prob, yes))
    n = len(scored)
    total = 0.0
    for bucket in bins:
        if not bucket:
            continue
        acc = sum(yes for _prob, yes in bucket) / len(bucket)
        conf = sum(prob for prob, _yes in bucket) / len(bucket)
        total += (len(bucket) / n) * abs(acc - conf)
    return total
