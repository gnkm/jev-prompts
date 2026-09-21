# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""McNemar の exact p。食い違いだけを見る。独立 2 標本は使わない。"""

from __future__ import annotations

import math


def mcnemar_p_value(n_baseline_only: int, n_other_only: int) -> float:
    """H0: 食い違いが半々のとき、観測以上に偏る両側確率。

    両方当たった・両方外れたマスは使わない。n=0 なら 1 を返す。
    """
    n = n_baseline_only + n_other_only
    if n == 0:
        return 1.0
    k = max(n_baseline_only, n_other_only)
    return min(1.0, 2.0 * _binom_tail_half(k, n))


def _binom_tail_half(k: int, n: int) -> float:
    """X ~ Binomial(n, 1/2) の P(X >= k)。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    log_term = (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        - n * math.log(2)
    )
    term = math.exp(log_term)
    total = term
    for i in range(k, n):
        term *= (n - i) / (i + 1)
        total += term
    return min(1.0, total)
