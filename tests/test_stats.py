# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""同じケース集合の A vs B1 に差と CI が出ること。p 値だけにはしない。"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from jev_prompts.config import BOOTSTRAP_REPLICATES, CI_LEVEL
from jev_prompts.runners import RequestLog, local_frame
from jev_prompts.stats import StatsError, compare_paired, holm_adjust, mcnemar_p_value

HASH_A = "a" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]


def _log(
    *,
    case_id: str,
    task: str,
    gold: str | int,
    answer: str | float,
    condition: str,
    split: str = "test",
    confidence: float | None = 0.5,
    error: str | None = None,
) -> RequestLog:
    return RequestLog(
        case_id=case_id,
        task=task,  # type: ignore[arg-type]
        condition=condition,  # type: ignore[arg-type]
        split=split,  # type: ignore[arg-type]
        probabilities={"x": 1.0},
        gold=gold,
        content_hash=HASH_A,
        model="typesafe/jev-1.13",
        answer=answer,
        confidence=confidence,
        usage_tokens=10,
        latency_ms=10.0,
        error=error,
        state_json={"query": "fixture"},
        question_json={"q": {"type": task}},
    )


def _row(frame: pl.DataFrame, **filters: str) -> dict[str, object]:
    view = frame
    for key, value in filters.items():
        view = view.filter(pl.col(key) == value)
    assert view.height == 1, view
    return view.to_dicts()[0]


def _choice_row(case_id: str, answer: str, condition: str) -> RequestLog:
    return _log(
        case_id=case_id,
        task="choice",
        gold="ham",
        answer=answer,
        condition=condition,
    )


def _choice_ab1() -> list[RequestLog]:
    """20件: 両方正 10、Aのみ 6、B1のみ 2、両方誤 2。"""
    logs: list[RequestLog] = []
    for i in range(10):
        cid = f"both-{i}"
        logs.extend((_choice_row(cid, "ham", "A"), _choice_row(cid, "ham", "B1")))
    for i in range(6):
        cid = f"a-only-{i}"
        logs.extend((_choice_row(cid, "ham", "A"), _choice_row(cid, "spam", "B1")))
    for i in range(2):
        cid = f"b-only-{i}"
        logs.extend((_choice_row(cid, "spam", "A"), _choice_row(cid, "ham", "B1")))
    for i in range(2):
        cid = f"none-{i}"
        logs.extend((_choice_row(cid, "spam", "A"), _choice_row(cid, "spam", "B1")))
    return logs


def test_mcnemar_exact_matches_hand_calculation() -> None:
    # 食い違い 8、6 対 2。2 * 37/256
    assert mcnemar_p_value(6, 2) == pytest.approx(74 / 256)
    assert mcnemar_p_value(0, 0) == 1.0


def test_holm_adjust_is_monotone_and_scaled() -> None:
    adjusted = holm_adjust([0.01, 0.04, 0.03])
    assert adjusted == pytest.approx([0.03, 0.06, 0.06])


def test_choice_a_vs_b1_reports_difference_and_ci() -> None:
    frame = compare_paired(local_frame(_choice_ab1()), n_bootstrap=BOOTSTRAP_REPLICATES)
    row = _row(frame, task="choice", other="B1", metric="accuracy")
    assert row["n_paired"] == 20
    assert row["value_baseline"] == pytest.approx(0.8)
    assert row["value_other"] == pytest.approx(0.6)
    assert row["difference"] == pytest.approx(0.2)
    assert row["ci_low"] is not None
    assert row["ci_high"] is not None
    assert float(row["ci_low"]) <= float(row["difference"]) <= float(row["ci_high"])
    assert row["ci_level"] == pytest.approx(CI_LEVEL)
    assert row["p_raw"] == pytest.approx(74 / 256)
    assert row["p_holm"] == pytest.approx(74 / 256)
    assert row["method"] == "mcnemar+bootstrap"
    assert row["n_baseline_only"] == 6
    assert row["n_other_only"] == 2
    assert row["n_discordant"] == 8
    assert row["n_bootstrap"] == 10_000
    assert "difference" in frame.columns
    assert "ci_low" in frame.columns
    assert "p_raw" in frame.columns


def test_unpaired_case_ids_are_not_compared() -> None:
    logs = [
        _log(case_id="a0", task="choice", gold="ham", answer="ham", condition="A"),
        _log(case_id="a1", task="choice", gold="ham", answer="ham", condition="A"),
        _log(case_id="x0", task="choice", gold="ham", answer="spam", condition="B1"),
        _log(case_id="x1", task="choice", gold="ham", answer="spam", condition="B1"),
    ]
    frame = compare_paired(local_frame(logs), n_bootstrap=50)
    assert frame.height == 0


def test_holm_covers_a_versus_each_condition() -> None:
    logs = _choice_ab1()
    extras: list[RequestLog] = []
    for log in logs:
        if log.condition != "A":
            continue
        extras.append(
            _log(
                case_id=log.case_id,
                task="choice",
                gold=str(log.gold),
                answer=log.answer or "ham",
                condition="B2",
            )
        )
        extras.append(
            _log(
                case_id=log.case_id,
                task="choice",
                gold=str(log.gold),
                answer=log.answer or "ham",
                condition="B3",
            )
        )
    frame = compare_paired(local_frame(logs + extras), n_bootstrap=200)
    acc = frame.filter(pl.col("metric") == "accuracy")
    others = set(acc["other"].to_list())
    assert others == {"B1", "B2", "B3"}
    b1 = _row(acc, other="B1")
    b2 = _row(acc, other="B2")
    assert float(b1["p_holm"]) >= float(b1["p_raw"])
    assert b2["p_raw"] == pytest.approx(1.0)
    assert float(b1["p_holm"]) == pytest.approx(float(b1["p_raw"]) * 3)


def test_score_mae_difference_has_ci() -> None:
    logs: list[RequestLog] = []
    golds = (0, 1, 2, 3)
    for i, gold in enumerate(golds):
        cid = f"s{i}"
        logs.append(
            _log(
                case_id=cid,
                task="score",
                gold=gold,
                answer=float(gold),
                condition="A",
            )
        )
        logs.append(
            _log(
                case_id=cid,
                task="score",
                gold=gold,
                answer=float(gold) + 1.0,
                condition="B1",
            )
        )
    row = _row(
        compare_paired(local_frame(logs), n_bootstrap=200),
        task="score",
        metric="mae",
        other="B1",
    )
    assert row["difference"] == pytest.approx(-1.0)
    assert row["ci_low"] == pytest.approx(-1.0)
    assert row["ci_high"] == pytest.approx(-1.0)
    assert row["method"] == "bootstrap"
    assert row["p_raw"] is not None


def test_ece_difference_has_paired_bootstrap_ci() -> None:
    logs: list[RequestLog] = []
    for i in range(4):
        cid = f"e{i}"
        logs.append(
            _log(
                case_id=cid,
                task="choice",
                gold="ham",
                answer="ham",
                condition="A",
                confidence=0.9,
            )
        )
        logs.append(
            _log(
                case_id=cid,
                task="choice",
                gold="ham",
                answer="spam" if i < 2 else "ham",
                condition="B1",
                confidence=0.9,
            )
        )
    # overwrite probabilities via local_frame after constructing with defaults
    frame = local_frame(logs).with_columns(
        pl.when(pl.col("condition") == "A")
        .then(pl.lit('{"ham":0.9,"spam":0.1}'))
        .otherwise(
            pl.when(pl.col("answer") == "ham")
            .then(pl.lit('{"ham":0.6,"spam":0.4}'))
            .otherwise(pl.lit('{"spam":0.6,"ham":0.4}'))
        )
        .alias("probabilities")
    )
    paired = compare_paired(frame, n_bootstrap=200)
    row = _row(paired, task="choice", metric="ece", other="B1")
    assert row["method"] == "bootstrap"
    assert row["ci_low"] is not None
    assert row["ci_high"] is not None
    assert float(row["ci_low"]) <= float(row["difference"]) <= float(row["ci_high"])
    conf_row = _row(paired, task="choice", metric="confidence", other="B1")
    assert conf_row["metric"] == "confidence"
    assert conf_row["difference"] == pytest.approx(0.0)


def test_noul_accuracy_is_mcnemar() -> None:
    logs: list[RequestLog] = []
    for i in range(4):
        cid = f"n{i}"
        a = 0.9 if i < 3 else 0.1
        b = 0.9 if i < 1 else 0.1
        logs.append(
            _log(case_id=cid, task="noul", gold="spam", answer=a, condition="A")
        )
        logs.append(
            _log(case_id=cid, task="noul", gold="spam", answer=b, condition="B1")
        )
    row = _row(
        compare_paired(local_frame(logs), n_bootstrap=200),
        task="noul",
        metric="accuracy",
        other="B1",
    )
    assert row["method"] == "mcnemar+bootstrap"
    assert row["difference"] == pytest.approx(0.5)
    assert row["ci_low"] is not None
    assert row["p_raw"] == pytest.approx(mcnemar_p_value(2, 0))


def test_missing_case_id_raises() -> None:
    logs = local_frame(
        [_log(case_id="c0", task="choice", gold="ham", answer="ham", condition="A")]
    ).drop("case_id")
    with pytest.raises(StatsError, match="case_id"):
        compare_paired(logs, n_bootstrap=10)


def test_duplicate_case_id_raises() -> None:
    logs = [
        _log(case_id="c0", task="choice", gold="ham", answer="ham", condition="A"),
        _log(case_id="c0", task="choice", gold="ham", answer="spam", condition="A"),
        _log(case_id="c0", task="choice", gold="ham", answer="ham", condition="B1"),
    ]
    with pytest.raises(StatsError, match="重複"):
        compare_paired(local_frame(logs), n_bootstrap=10)


def test_bootstrap_replicates_default_is_ten_thousand() -> None:
    assert BOOTSTRAP_REPLICATES == 10_000


def test_stats_source_does_not_use_two_sample_tests() -> None:
    root = REPO_ROOT / "src" / "jev_prompts" / "stats"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    lowered = text.lower()
    assert "ttest" not in lowered
    assert "mannwhitney" not in lowered
    assert "welch" not in lowered
    assert "independent" not in lowered or "独立 2 標本は使わない" in text


def test_invalid_bootstrap_args_raise() -> None:
    logs = local_frame(_choice_ab1())
    with pytest.raises(StatsError, match="n_bootstrap"):
        compare_paired(logs, n_bootstrap=0)
    with pytest.raises(StatsError, match="n_bootstrap"):
        compare_paired(logs, n_bootstrap=-1)
    with pytest.raises(StatsError, match="ci_level"):
        compare_paired(logs, n_bootstrap=10, ci_level=1.5)
    with pytest.raises(StatsError, match="ci_level"):
        compare_paired(logs, n_bootstrap=10, ci_level=0.0)


def test_n_bootstrap_counts_defined_replicates() -> None:
    logs: list[RequestLog] = []
    golds = ("spam", "ham", "ham", "ham")
    for i, gold in enumerate(golds):
        cid = f"u{i}"
        pred_pos = gold == "spam"
        logs.append(
            _log(
                case_id=cid,
                task="noul",
                gold=gold,
                answer=0.8 if pred_pos else 0.2,
                condition="A",
            )
        )
        logs.append(
            _log(
                case_id=cid,
                task="noul",
                gold=gold,
                answer=0.7 if pred_pos else 0.3,
                condition="B1",
            )
        )
    requested = 200
    frame = compare_paired(local_frame(logs), n_bootstrap=requested)
    auc = _row(frame, metric="auc")
    acc = _row(frame, metric="accuracy")
    assert acc["n_bootstrap"] == requested
    assert 0 < int(auc["n_bootstrap"]) < requested
