# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""既知の RequestLog フィクスチャで指標が手計算と一致すること。"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from jev_prompts.metrics import (
    METRIC_COLUMNS,
    MetricsError,
    aggregate_metrics,
    prepare_cases,
)
from jev_prompts.runners import RequestLog, local_frame, to_published

HASH_A = "a" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]


def _log(
    *,
    case_id: str,
    task: str,
    gold: str | int,
    answer: str | float,
    condition: str = "A",
    split: str = "test",
    confidence: float | None = 0.5,
    usage_tokens: int | None = 10,
    latency_ms: float | None = 10.0,
    error: str | None = None,
    probabilities: dict[str, float] | None = None,
) -> RequestLog:
    probs = probabilities if probabilities is not None else {"x": 1.0}
    return RequestLog(
        case_id=case_id,
        task=task,  # type: ignore[arg-type]
        condition=condition,  # type: ignore[arg-type]
        split=split,  # type: ignore[arg-type]
        probabilities=probs,
        gold=gold,
        content_hash=HASH_A,
        model="typesafe/jev-1.13",
        answer=answer,
        confidence=confidence,
        usage_tokens=usage_tokens,
        latency_ms=latency_ms,
        error=error,
        state_json={"query": "fixture"},
        question_json={"q": {"type": task}},
    )


def _row(metrics: pl.DataFrame, **filters: str) -> dict[str, object]:
    frame = metrics
    for key, value in filters.items():
        frame = frame.filter(pl.col(key) == value)
    assert frame.height == 1, frame
    return frame.to_dicts()[0]


def test_choice_top1_matches_hand_calculation() -> None:
    # 4件中 3 件一致 → 0.75
    logs = local_frame(
        [
            _log(case_id="c0", task="choice", gold="ham", answer="ham"),
            _log(case_id="c1", task="choice", gold="spam", answer="spam"),
            _log(case_id="c2", task="choice", gold="ham", answer="spam"),
            _log(case_id="c3", task="choice", gold="spam", answer="spam"),
        ]
    )
    row = _row(aggregate_metrics(logs), task="choice")
    assert row["top1"] == pytest.approx(0.75)
    assert row["n"] == 4
    assert row["n_error"] == 0
    assert row["n_primary"] == 4
    assert row["error_rate"] == pytest.approx(0.0)
    assert row["mae"] is None
    assert row["spearman"] is None
    assert row["auc"] is None


def test_choice_parse_failure_counts_as_incorrect() -> None:
    logs = local_frame(
        [
            _log(case_id="c0", task="choice", gold="ham", answer="ham"),
            RequestLog.failed(
                case_id="c1",
                task="choice",
                condition="A",
                split="test",
                gold="ham",
                content_hash=HASH_A,
                error="parse",
            ),
        ]
    )
    row = _row(aggregate_metrics(logs), task="choice")
    assert row["top1"] == pytest.approx(0.5)
    assert row["n"] == 2
    assert row["n_error"] == 1
    assert row["n_primary"] == 2
    assert row["error_rate"] == pytest.approx(0.5)


def test_score_mae_does_not_round() -> None:
    # gold 0,1,2,3 / score 0.4,1.4,1.6,2.6
    # 未丸め MAE = (0.4+0.4+0.4+0.4)/4 = 0.4
    # 最近段階に丸めると全て一致して MAE は 0 になる
    logs = local_frame(
        [
            _log(case_id="s0", task="score", gold=0, answer=0.4),
            _log(case_id="s1", task="score", gold=1, answer=1.4),
            _log(case_id="s2", task="score", gold=2, answer=1.6),
            _log(case_id="s3", task="score", gold=3, answer=2.6),
        ]
    )
    row = _row(aggregate_metrics(logs), task="score")
    assert row["mae"] == pytest.approx(0.4)
    assert row["n_primary"] == 4
    assert row["error_rate"] == pytest.approx(0.0)
    rounded = [round(x) for x in (0.4, 1.4, 1.6, 2.6)]
    assert rounded == [0, 1, 2, 3]
    assert sum(abs(a - b) for a, b in zip(rounded, (0, 1, 2, 3), strict=True)) == 0
    assert row["top1"] is None
    assert row["auc"] is None


def test_score_spearman_matches_hand_calculation() -> None:
    # gold 順位 1,2,3,4 / score 0.1,2.0,1.0,3.0 の順位 1,3,2,4
    # d^2 = 0+1+1+0 = 2, rho = 1 - 6*2/(4*15) = 0.8
    logs = local_frame(
        [
            _log(case_id="s0", task="score", gold=0, answer=0.1),
            _log(case_id="s1", task="score", gold=1, answer=2.0),
            _log(case_id="s2", task="score", gold=2, answer=1.0),
            _log(case_id="s3", task="score", gold=3, answer=3.0),
        ]
    )
    row = _row(aggregate_metrics(logs), task="score")
    assert row["spearman"] == pytest.approx(0.8)
    assert row["mae"] == pytest.approx((0.1 + 1.0 + 1.0 + 0.0) / 4)


def test_noul_auc_does_not_invert() -> None:
    # yes: 0.1, 0.2 / no: 0.8, 0.9 → 4 対すべて no のほうが高いので AUC=0
    # 反転補正すると 1 になるが、生値のまま 0 を出す
    logs = local_frame(
        [
            _log(case_id="n0", task="noul", gold="yes", answer=0.1),
            _log(case_id="n1", task="noul", gold="yes", answer=0.2),
            _log(case_id="n2", task="noul", gold="no", answer=0.8),
            _log(case_id="n3", task="noul", gold="no", answer=0.9),
        ]
    )
    row = _row(aggregate_metrics(logs), task="noul")
    assert row["auc"] == pytest.approx(0.0)
    assert row["n_primary"] == 4
    assert 1.0 - row["auc"] == pytest.approx(1.0)
    assert row["top1"] is None
    assert row["mae"] is None


def test_noul_llm_labels_count_as_primary() -> None:
    logs = local_frame(
        [
            _log(case_id="n0", task="noul", gold="yes", answer="spam"),
            _log(case_id="n1", task="noul", gold="no", answer="ham"),
            _log(case_id="n2", task="noul", gold="yes", answer="ham"),
            _log(case_id="n3", task="noul", gold="no", answer="spam"),
        ]
    )
    row = _row(aggregate_metrics(logs), task="noul")
    assert row["n_primary"] == 4
    assert row["auc"] == pytest.approx(0.5)


def test_score_llm_labels_count_as_primary() -> None:
    logs = local_frame(
        [
            _log(case_id="s0", task="score", gold=1, answer="C"),
            _log(case_id="s1", task="score", gold=2, answer="S"),
        ]
    )
    row = _row(aggregate_metrics(logs), task="score")
    assert row["n_primary"] == 2
    assert row["mae"] == pytest.approx(0.0)


def test_noul_auc_partial_pairs() -> None:
    # yes: 0.9, 0.3 / no: 0.4, 0.2 → 勝ち 3 / 4 = 0.75
    logs = local_frame(
        [
            _log(case_id="n0", task="noul", gold="spam", answer=0.9),
            _log(case_id="n1", task="noul", gold="spam", answer=0.3),
            _log(case_id="n2", task="noul", gold="ham", answer=0.4),
            _log(case_id="n3", task="noul", gold="ham", answer=0.2),
        ]
    )
    row = _row(aggregate_metrics(logs), task="noul")
    assert row["auc"] == pytest.approx(0.75)


def test_confident_error_rate_choice() -> None:
    # conf>=0.9 かつ不正解は 2/4
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="ham",
                answer="ham",
                confidence=0.95,
            ),
            _log(
                case_id="c1",
                task="choice",
                gold="ham",
                answer="spam",
                confidence=0.95,
            ),
            _log(
                case_id="c2",
                task="choice",
                gold="ham",
                answer="spam",
                confidence=0.5,
            ),
            _log(
                case_id="c3",
                task="choice",
                gold="ham",
                answer="spam",
                confidence=0.99,
            ),
        ]
    )
    row = _row(aggregate_metrics(logs), task="choice")
    assert row["confident_error_rate"] == pytest.approx(0.5)


def test_confident_error_rate_noul_uses_extremes() -> None:
    # 0.05 (gold yes) と 0.95 (gold no) が confident 誤答。4 件中 2 件。
    logs = local_frame(
        [
            _log(case_id="n0", task="noul", gold="yes", answer=0.05, confidence=None),
            _log(case_id="n1", task="noul", gold="no", answer=0.95, confidence=None),
            _log(case_id="n2", task="noul", gold="yes", answer=0.6, confidence=None),
            _log(case_id="n3", task="noul", gold="no", answer=0.4, confidence=None),
        ]
    )
    row = _row(aggregate_metrics(logs), task="noul")
    assert row["confident_error_rate"] == pytest.approx(0.5)


def test_ece_ten_bins_matches_hand_calculation() -> None:
    # bin1: (0.15, correct) → |1-0.15|*1/4
    # bin2: (0.25, wrong), (0.21, correct) → |0.5-0.23|*2/4
    # bin9: (0.95, correct) → |1-0.95|*1/4
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                confidence=0.15,
                probabilities={"a": 0.15, "b": 0.85},
            ),
            _log(
                case_id="c1",
                task="choice",
                gold="a",
                answer="b",
                confidence=0.25,
                probabilities={"b": 0.25, "a": 0.75},
            ),
            _log(
                case_id="c2",
                task="choice",
                gold="a",
                answer="a",
                confidence=0.21,
                probabilities={"a": 0.21, "b": 0.79},
            ),
            _log(
                case_id="c3",
                task="choice",
                gold="a",
                answer="a",
                confidence=0.95,
                probabilities={"a": 0.95, "b": 0.05},
            ),
        ]
    )
    expected = (0.25 * abs(1 - 0.15)) + (0.5 * abs(0.5 - 0.23)) + (0.25 * abs(1 - 0.95))
    row = _row(aggregate_metrics(logs), task="choice")
    assert row["ece"] == pytest.approx(expected)


def test_tokens_per_1000_and_latency_percentiles() -> None:
    # tokens 10,20,30 → 平均 20 → 1000 件あたり 20000
    # latency 10,20,30,40,50 → 線形補間 p50=30, p95=48
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                usage_tokens=10,
                latency_ms=10,
            ),
            _log(
                case_id="c1",
                task="choice",
                gold="a",
                answer="a",
                usage_tokens=20,
                latency_ms=20,
            ),
            _log(
                case_id="c2",
                task="choice",
                gold="a",
                answer="a",
                usage_tokens=30,
                latency_ms=30,
            ),
            _log(
                case_id="c3",
                task="choice",
                gold="a",
                answer="a",
                usage_tokens=20,
                latency_ms=40,
            ),
            _log(
                case_id="c4",
                task="choice",
                gold="a",
                answer="a",
                usage_tokens=20,
                latency_ms=50,
            ),
        ]
    )
    row = _row(aggregate_metrics(logs), task="choice")
    assert row["tokens_per_1000"] == pytest.approx(20_000)
    assert row["latency_p50_ms"] == pytest.approx(30.0)
    assert row["latency_p95_ms"] == pytest.approx(48.0)


def test_groups_by_condition_and_uses_polars() -> None:
    logs = local_frame(
        [
            _log(case_id="c0", task="choice", gold="a", answer="a", condition="A"),
            _log(case_id="c1", task="choice", gold="a", answer="b", condition="A"),
            _log(case_id="c0", task="choice", gold="a", answer="a", condition="B1"),
            _log(case_id="c1", task="choice", gold="a", answer="a", condition="B1"),
        ]
    )
    metrics = aggregate_metrics(logs)
    assert isinstance(metrics, pl.DataFrame)
    assert list(metrics.columns) == list(METRIC_COLUMNS)
    assert _row(metrics, condition="A")["top1"] == pytest.approx(0.5)
    assert _row(metrics, condition="B1")["top1"] == pytest.approx(1.0)


def test_pass_lines_are_not_metric_columns() -> None:
    logs = local_frame([_log(case_id="c0", task="choice", gold="a", answer="a")])
    metrics = aggregate_metrics(logs)
    joined = " ".join(metrics.columns)
    assert "pass" not in joined.lower()
    assert "合格" not in joined
    src = (REPO_ROOT / "src/jev_prompts/metrics/aggregate.py").read_text(
        encoding="utf-8"
    )
    assert "+5" not in src
    assert "0.05" not in src
    assert "-0.2" not in src


def test_published_records_are_aggregatable() -> None:
    local = local_frame([_log(case_id="c0", task="choice", gold="ham", answer="ham")])
    published = to_published(local)
    row = _row(aggregate_metrics(published), task="choice")
    assert row["top1"] == pytest.approx(1.0)


def test_score_errors_are_excluded_from_mae_but_counted() -> None:
    # 成功 2 件の MAE は |1.0-1|+|2.0-2| / 2 = 0。失敗 1 件は error_rate に出す。
    logs = local_frame(
        [
            _log(case_id="s0", task="score", gold=1, answer=1.0),
            _log(case_id="s1", task="score", gold=2, answer=2.0),
            RequestLog.failed(
                case_id="s2",
                task="score",
                condition="A",
                split="test",
                gold=3,
                content_hash=HASH_A,
                error="parse",
            ),
        ]
    )
    row = _row(aggregate_metrics(logs), task="score")
    assert row["n"] == 3
    assert row["n_error"] == 1
    assert row["n_primary"] == 2
    assert row["error_rate"] == pytest.approx(1 / 3)
    assert row["mae"] == pytest.approx(0.0)


def test_rejects_noul_outside_unit_interval() -> None:
    logs = local_frame([_log(case_id="n0", task="noul", gold="yes", answer=1.5)])
    with pytest.raises(MetricsError, match="0〜1"):
        aggregate_metrics(logs)


def test_rejects_non_finite_confidence() -> None:
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                confidence=float("nan"),
            )
        ]
    )
    with pytest.raises(MetricsError, match="0〜1"):
        aggregate_metrics(logs)


def test_missing_columns_raise() -> None:
    with pytest.raises(MetricsError, match="必須列"):
        aggregate_metrics(pl.DataFrame({"task": ["choice"]}))


def test_choice_ece_uses_adopted_label_probability() -> None:
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="ham",
                answer="ham",
                confidence=0.99,
                probabilities={"ham": 0.60, "spam": 0.40},
            ),
            _log(
                case_id="c1",
                task="choice",
                gold="ham",
                answer="spam",
                confidence=0.99,
                probabilities={"spam": 0.20, "ham": 0.80},
            ),
        ]
    )
    row = _row(aggregate_metrics(logs), task="choice")
    expected = 0.5 * abs(1.0 - 0.60) + 0.5 * abs(0.0 - 0.20)
    assert row["ece"] == pytest.approx(expected)
    assert row["brier"] == pytest.approx(((0.60 - 1.0) ** 2 + (0.20 - 0.0) ** 2) / 2)
    prepared = prepare_cases(logs)
    assert prepared["cal_probability"].to_list() == pytest.approx([0.60, 0.20])
    assert prepared["confidence"].to_list() == pytest.approx([0.99, 0.99])


def test_score_ece_uses_rounded_stage_not_mode() -> None:
    logs = local_frame(
        [
            _log(
                case_id="s0",
                task="score",
                gold=2,
                answer=2.46,
                confidence=0.46,
                probabilities={"0": 0.03, "1": 0.01, "2": 0.41, "3": 0.55},
            )
        ]
    )
    row = _row(aggregate_metrics(logs), task="score")
    assert round(2.46) == 2
    assert row["ece"] == pytest.approx(abs(1.0 - 0.41))
    assert row["brier"] == pytest.approx((0.41 - 1.0) ** 2)
    prepared = prepare_cases(logs)
    assert prepared["cal_probability"][0] == pytest.approx(0.41)
    assert prepared["score_stage"][0] == 2


def test_jev_noul_ece_uses_max_p_when_confidence_is_null() -> None:
    logs = local_frame(
        [
            _log(
                case_id="n0",
                task="noul",
                gold="yes",
                answer=0.2,
                confidence=None,
                probabilities={"yes": 0.2, "no": 0.8},
            )
        ]
    )
    row = _row(aggregate_metrics(logs), task="noul")
    assert row["ece"] == pytest.approx(abs(0.0 - 0.8))
    assert row["brier"] == pytest.approx((0.8 - 0.0) ** 2)
    prepared = prepare_cases(logs)
    assert prepared["confidence"][0] is None
    assert prepared["cal_probability"][0] == pytest.approx(0.8)


def test_llm_noul_ece_uses_self_reported_confidence() -> None:
    logs = local_frame(
        [
            _log(
                case_id="n0",
                task="noul",
                gold="yes",
                answer="spam",
                confidence=0.7,
                probabilities={"label": 0.3},
            )
        ]
    )
    row = _row(aggregate_metrics(logs), task="noul")
    assert row["ece"] == pytest.approx(abs(1.0 - 0.7))
    assert row["brier"] == pytest.approx((0.7 - 1.0) ** 2)
    prepared = prepare_cases(logs)
    assert prepared["cal_probability"][0] == pytest.approx(0.7)
    assert prepared["pred"][0] == pytest.approx(1.0)


def test_signal_auroc_ranks_correct_above_incorrect() -> None:
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="ham",
                answer="ham",
                confidence=0.9,
                probabilities={"ham": 0.6, "spam": 0.4},
            ),
            _log(
                case_id="c1",
                task="choice",
                gold="ham",
                answer="spam",
                confidence=0.1,
                probabilities={"spam": 0.55, "ham": 0.45},
            ),
        ]
    )
    row = _row(aggregate_metrics(logs), task="choice")
    assert row["signal_auroc"] == pytest.approx(1.0)


def test_design_doc_defines_metrics() -> None:
    design = (REPO_ROOT / "docs/source-of-truth/design-of-evaluation.md").read_text(
        encoding="utf-8"
    )
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "top-1" in design
    assert "MAE" in design
    assert "Spearman" in design
    assert "AUC" in design
    assert "合格ライン" in design
    assert "design-of-evaluation.md" in readme
