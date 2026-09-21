# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""H1〜H4 と A の誤答内訳。公開物に本文キーは書かない。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from jev_prompts.config.metrics import CONFIDENT_THRESHOLD
from jev_prompts.metrics import aggregate_metrics
from jev_prompts.report.a_errors import MODE_LABELS, classify_a_errors
from jev_prompts.report.forbidden import reject_forbidden_text
from jev_prompts.report.prices import ModelPrice, render_prices
from jev_prompts.report.tables import fmt_float, markdown_table
from jev_prompts.stats.compare import compare_paired

_PRIMARY = {"choice": "top1", "score": "mae", "noul": "auc"}
_H1_DELTA = {"choice": 0.05, "score": 0.2, "noul": 0.05}
_TASKS = ("choice", "score", "noul")


def render_findings(
    logs: pl.DataFrame,
    *,
    prices: tuple[ModelPrice, ...] | None = None,
    measured_on: date,
    errors: pl.DataFrame | None = None,
) -> str:
    metrics = aggregate_metrics(logs)
    paired = compare_paired(logs) if logs.height else pl.DataFrame()
    counted = errors if errors is not None else classify_a_errors(logs)
    parts = [
        "# 本ラン報告",
        "",
        f"測定日: {measured_on.isoformat()}",
        "",
        "test 分割のみ。入力本文は置かない。",
        "",
    ]
    if prices:
        parts.extend(render_prices(prices, measured_on=measured_on).splitlines()[1:])
        parts.append("")
    parts.extend(_h1_section(metrics))
    parts.extend(_h2_section(metrics))
    parts.extend(_h3_section(metrics))
    parts.extend(_h4_section(metrics))
    parts.extend(_errors_section(counted))
    if paired.height:
        parts.extend(
            [
                "## 対応あり比較（A 対 他条件）",
                "",
                markdown_table(
                    paired,
                    [
                        "task",
                        "other",
                        "metric",
                        "difference",
                        "ci_low",
                        "ci_high",
                        "p_holm",
                    ],
                    formatters={
                        "difference": fmt_float,
                        "ci_low": fmt_float,
                        "ci_high": fmt_float,
                        "p_holm": fmt_float,
                    },
                ),
                "",
            ]
        )
    text = "\n".join(parts)
    reject_forbidden_text(text, source="findings.md")
    return text


def write_findings(
    logs: pl.DataFrame,
    dest: Path,
    *,
    prices: tuple[ModelPrice, ...] | None = None,
    measured_on: date,
    errors: pl.DataFrame | None = None,
) -> Path:
    text = render_findings(logs, prices=prices, measured_on=measured_on, errors=errors)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def _metric_row(metrics: pl.DataFrame, task: str, condition: str) -> dict | None:
    subset = metrics.filter(
        (pl.col("task") == task) & (pl.col("condition") == condition)
    )
    if subset.height == 0:
        return None
    return subset.to_dicts()[0]


def _verdict(flag: bool | None) -> str:
    if flag is None:
        return "判定不能"
    return "支持" if flag else "棄却"


def _h1_section(metrics: pl.DataFrame) -> list[str]:
    flags: list[bool] = []
    lines = [
        "## H1",
        "",
        "一般的な LLM 向けの書き方をそのまま移植すると、"
        "jev 用に書いた場合より精度が落ちる。",
        "",
    ]
    for task in _TASKS:
        ok, detail = _h1_task(metrics, task)
        if ok is not None:
            flags.append(ok)
        lines.append(f"- {detail}")
    conf_ok, conf_detail = _h1_confidence(metrics)
    lines.append(f"- {conf_detail}")
    passed = (sum(flags) >= 2 and conf_ok is True) if flags else None
    lines.append(
        f"- 判定: {_verdict(passed)}"
        "（3 課題中 2 以上で主指標の差、かつ confident 誤答が B1 の半分以下）"
    )
    lines.append("")
    return lines


def _h1_task(metrics: pl.DataFrame, task: str) -> tuple[bool | None, str]:
    primary = _PRIMARY[task]
    a = _metric_row(metrics, task, "A")
    b1 = _metric_row(metrics, task, "B1")
    if a is None or b1 is None:
        return None, f"{task}: A または B1 が無い"
    va, vb = a.get(primary), b1.get(primary)
    if va is None or vb is None:
        return None, f"{task}: {primary} が無い"
    delta = _H1_DELTA[task]
    if task == "score":
        ok = float(vb) - float(va) >= delta
        return ok, (
            f"{task}: MAE A={fmt_float(va)} B1={fmt_float(vb)} "
            f"（B1-A が {delta} 以上なら通過）"
        )
    ok = float(va) - float(vb) >= delta
    return ok, (
        f"{task}: {primary} A={fmt_float(va)} B1={fmt_float(vb)} "
        f"（A-B1 が {delta} 以上なら通過）"
    )


def _h1_confidence(metrics: pl.DataFrame) -> tuple[bool | None, str]:
    rates: list[tuple[str, float, float]] = []
    for task in _TASKS:
        a = _metric_row(metrics, task, "A")
        b1 = _metric_row(metrics, task, "B1")
        if a is None or b1 is None:
            continue
        ca, cb = a.get("confident_error_rate"), b1.get("confident_error_rate")
        if ca is None or cb is None:
            continue
        rates.append((task, float(ca), float(cb)))
    if not rates:
        return None, "confident 誤答率が無い"
    ok = all(ca <= 0.5 * cb if cb > 0 else ca == 0 for _task, ca, cb in rates)
    bits = [f"{task}: A={fmt_float(ca)} B1={fmt_float(cb)}" for task, ca, cb in rates]
    joined = "; ".join(bits)
    return ok, f"confident 誤答率（閾値 {fmt_float(CONFIDENT_THRESHOLD)}）: {joined}"


def _h2_section(metrics: pl.DataFrame) -> list[str]:
    lines = [
        "## H2",
        "",
        "失敗モードによって効き方の大きさが違う（B2 / B3 / C の A からの低下）。",
        "",
    ]
    found = False
    for task in _TASKS:
        a = _metric_row(metrics, task, "A")
        if a is None:
            continue
        found = True
        primary = _PRIMARY[task]
        base = a.get(primary)
        bits = [f"A={fmt_float(base)}"]
        for cond in ("B2", "B3", "C"):
            bits.append(_delta_bit(metrics, task, cond, primary, base))
        lines.append(f"- {task}: " + "; ".join(bits))
    if not found:
        lines.append("比較できる行が無い。")
    else:
        lines.append("- 判定: 差の順位を上表どおり記録する（事前に順位は固定しない）。")
    lines.append("")
    return lines


def _delta_bit(
    metrics: pl.DataFrame,
    task: str,
    cond: str,
    primary: str,
    base: object,
) -> str:
    row = _metric_row(metrics, task, cond)
    if row is None:
        return f"{cond}= "
    value = row.get(primary)
    if base is None or value is None:
        return f"{cond}={fmt_float(value)}"
    if task == "score":
        delta = float(value) - float(base)
    else:
        delta = float(base) - float(value)
    return f"{cond}={fmt_float(value)} (Δ={fmt_float(delta)})"


def _h3_section(metrics: pl.DataFrame) -> list[str]:
    lines = [
        "## H3",
        "",
        "confidence は誤答の予測子として使える。"
        "良いプロンプトほど自信のある誤答が少ない。",
        "",
    ]
    if metrics.height == 0:
        lines.extend(["較正指標が無い。", ""])
        return lines
    frame = metrics.select("task", "condition", "confident_error_rate", "ece")
    lines.append(
        markdown_table(
            frame,
            ["task", "condition", "confident_error_rate", "ece"],
            formatters={"confident_error_rate": fmt_float, "ece": fmt_float},
        )
    )
    a = metrics.filter(pl.col("condition") == "A")["confident_error_rate"].to_list()
    b1 = metrics.filter(pl.col("condition") == "B1")["confident_error_rate"].to_list()
    if a and b1 and None not in a and None not in b1:
        better = sum(float(x) for x in a) < sum(float(x) for x in b1)
        verdict = _verdict(better)
    else:
        verdict = "判定不能"
    lines.extend([f"- 判定: {verdict}（A の confident 誤答率が B1 より小さいか）", ""])
    return lines


def _h4_section(metrics: pl.DataFrame) -> list[str]:
    lines = [
        "## H4",
        "",
        "良いプロンプトの jev は、素朴な LLM と同等以上の精度を"
        "より低いコストと遅延で出す。",
        "",
    ]
    if metrics.height == 0:
        lines.extend(["コスト行が無い。", ""])
        return lines
    frame = metrics.select(
        "task",
        "condition",
        "tokens_per_1000",
        "latency_p95_ms",
        "top1",
        "mae",
        "auc",
    )
    lines.append(
        markdown_table(
            frame,
            [
                "task",
                "condition",
                "tokens_per_1000",
                "latency_p95_ms",
                "top1",
                "mae",
                "auc",
            ],
            formatters={
                "tokens_per_1000": fmt_float,
                "latency_p95_ms": fmt_float,
                "top1": fmt_float,
                "mae": fmt_float,
                "auc": fmt_float,
            },
        )
    )
    notes: list[str] = []
    wins: list[bool] = []
    for task in _TASKS:
        bit = _h4_task(metrics, task)
        if bit is None:
            continue
        ok, text = bit
        wins.append(ok)
        notes.append(text)
    extra = notes or ["- L1 と比較できる行が無い"]
    verdict = _verdict(all(wins) if wins else None)
    lines.extend([*extra, f"- 判定: {verdict}", ""])
    return lines


def _h4_task(metrics: pl.DataFrame, task: str) -> tuple[bool, str] | None:
    a = _metric_row(metrics, task, "A")
    l1 = _metric_row(metrics, task, "L1")
    if a is None or l1 is None:
        return None
    primary = _PRIMARY[task]
    va, vl = a.get(primary), l1.get(primary)
    ca, cl = a.get("tokens_per_1000"), l1.get("tokens_per_1000")
    da, dl = a.get("latency_p95_ms"), l1.get("latency_p95_ms")
    if None in (va, vl, ca, cl, da, dl):
        return None
    acc_ok = float(va) <= float(vl) if task == "score" else float(va) >= float(vl)
    cheap = float(ca) <= float(cl)
    fast = float(da) <= float(dl)
    ok = acc_ok and cheap and fast
    return ok, f"- {task}: 精度OK={acc_ok} トークンOK={cheap} p95OK={fast}"


def _errors_section(errors: pl.DataFrame) -> list[str]:
    lines = [
        "## A の誤答",
        "",
        "目視分類の内訳。本文は載せていない。",
        "",
    ]
    if errors.height == 0:
        lines.extend(["A の誤答は無かった。", ""])
        return lines
    labeled = errors.with_columns(
        pl.col("mode").replace_strict(MODE_LABELS, default=pl.col("mode"))
    )
    lines.append(
        markdown_table(
            labeled,
            ["task", "mode", "n"],
            formatters={"n": _fmt_count},
        )
    )
    lines.append("")
    return lines


def _fmt_count(value: object) -> str:
    if value is None:
        return ""
    return str(int(value))
