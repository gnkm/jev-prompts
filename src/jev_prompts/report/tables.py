# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""Polars の表を markdown にする。"""

from collections.abc import Mapping, Sequence

import polars as pl


def fmt_float(value: object, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def fmt_ci(low: object, high: object, digits: int = 3) -> str:
    if low is None or high is None:
        return ""
    return f"[{fmt_float(low, digits)}, {fmt_float(high, digits)}]"


def fmt_int(value: object) -> str:
    if value is None:
        return ""
    return str(int(value))


def markdown_table(
    frame: pl.DataFrame,
    columns: Sequence[str],
    *,
    labels: Mapping[str, str] | None = None,
    formatters: Mapping[str, object] | None = None,
) -> str:
    if frame.height == 0:
        return ""
    names = labels or {}
    header = [names.get(col, col) for col in columns]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    funcs = formatters or {}
    for row in frame.select(list(columns)).iter_rows(named=True):
        cells = [_cell(row[col], funcs.get(col)) for col in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _cell(value: object, formatter: object) -> str:
    if formatter is None:
        return "" if value is None else str(value)
    return str(formatter(value))  # type: ignore[operator]
