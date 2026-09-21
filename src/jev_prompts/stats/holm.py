# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""Holm の調整 p。A 対各条件のように同じデータで何度も判定するとき用。"""

from __future__ import annotations


def holm_adjust(p_values: list[float]) -> list[float]:
    """入力順のまま、Holm の単調な調整 p を返す。空なら空。"""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(order):
        scaled = min(1.0, p_values[index] * (m - rank))
        running = max(running, scaled)
        adjusted[index] = running
    return adjusted
