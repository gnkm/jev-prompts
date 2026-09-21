# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""対応ありブートストラップ。1 チケットは同じケースの 2 条件分。"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence

Stat = Callable[[Sequence[object]], float | None]


def percentile_ci(samples: Sequence[float], level: float) -> tuple[float, float]:
    """線形補間の分位点で両側区間を返す。"""
    ordered = sorted(samples)
    tail = (1.0 - level) / 2.0
    return (_quantile(ordered, tail), _quantile(ordered, 1.0 - tail))


def bootstrap_two_sided_p(diffs: Sequence[float]) -> float:
    """差のブートストラップ分布が 0 をまたぐ程度。両側。"""
    n = len(diffs)
    if n == 0:
        return 1.0
    ge = sum(1 for value in diffs if value >= 0) / n
    le = sum(1 for value in diffs if value <= 0) / n
    return min(1.0, 2.0 * min(ge, le))


def paired_bootstrap_diffs(
    left: Sequence[object],
    right: Sequence[object],
    stat: Stat,
    *,
    n_bootstrap: int,
    rng: random.Random,
) -> list[float]:
    """同じ添字を同時に再標本し、stat(left)-stat(right) を積む。"""
    n = len(left)
    if n == 0 or n != len(right):
        return []
    diffs: list[float] = []
    for _ in range(n_bootstrap):
        idx = [rng.randrange(n) for _ in range(n)]
        a = stat([left[i] for i in idx])
        b = stat([right[i] for i in idx])
        if a is None or b is None:
            continue
        diffs.append(a - b)
    return diffs


def _quantile(ordered: Sequence[float], p: float) -> float:
    n = len(ordered)
    if n == 1:
        return float(ordered[0])
    pos = p * (n - 1)
    left = int(pos)
    right = min(left + 1, n - 1)
    weight = pos - left
    return float(ordered[left]) * (1.0 - weight) + float(ordered[right]) * weight
