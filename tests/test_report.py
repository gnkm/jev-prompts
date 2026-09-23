# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開 markdown に図リンクがあり、本文キーが残らないこと。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from jev_prompts.config import ECE_BINS
from jev_prompts.report import (
    FORBIDDEN_TOKENS,
    ReportError,
    calibration_table,
    risk_coverage_table,
    write_report,
)
from jev_prompts.report.cli import app
from jev_prompts.runners import (
    RequestLog,
    local_frame,
    published_frame,
    write_published_records,
)

HASH_A = "a" * 64
REPO_ROOT = Path(__file__).resolve().parents[1]
N_BOOT = 80


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
    probabilities: dict[str, float] | None = None,
) -> RequestLog:
    return RequestLog(
        case_id=case_id,
        task=task,  # type: ignore[arg-type]
        condition=condition,  # type: ignore[arg-type]
        split=split,  # type: ignore[arg-type]
        probabilities=probabilities if probabilities is not None else {"x": 1.0},
        gold=gold,
        content_hash=HASH_A,
        model="typesafe/jev-1.13",
        answer=answer,
        confidence=confidence,
        usage_tokens=usage_tokens,
        latency_ms=latency_ms,
        state_json={"query": "secret-query", "message": "secret-message"},
        question_json={"q": {"type": task, "query": "nested-query"}},
    )


def _choice_logs() -> list[RequestLog]:
    # ECE 手計算と同じ 4 件 + 条件 L1 をコスト散布用に足す
    shared = [
        ("c0", "a", "a", 0.15, 10),
        ("c1", "a", "b", 0.25, 20),
        ("c2", "a", "a", 0.21, 30),
        ("c3", "a", "a", 0.95, 40),
    ]
    logs: list[RequestLog] = []
    for condition, tokens_shift in (("A", 0), ("L1", 50)):
        for case_id, gold, answer, conf, tokens in shared:
            logs.append(
                _log(
                    case_id=f"{condition}-{case_id}",
                    task="choice",
                    gold=gold,
                    answer=answer,
                    condition=condition,
                    confidence=conf,
                    usage_tokens=tokens + tokens_shift,
                    probabilities={answer: conf, "other": max(0.0, 1.0 - conf)},
                )
            )
    return logs


def _scan_public(paths: list[Path]) -> None:
    for path in paths:
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"{path} に {token}"
        assert "secret-query" not in text
        assert "secret-message" not in text


def test_write_report_links_figures_and_omits_body(tmp_path: Path) -> None:
    dest = tmp_path / "results"
    written = write_report(local_frame(_choice_logs()), dest, n_bootstrap=N_BOOT)
    text = written.markdown.read_text(encoding="utf-8")
    assert written.markdown.name == "tables.md"
    assert "](figures/reliability-choice.svg)" in text
    assert "risk-coverage" not in text
    assert "](figures/cost-accuracy-choice.svg)" in text
    assert "測定表" in text
    assert "概要" not in text
    assert "考察" not in text
    reliability = dest / "figures/reliability-choice.svg"
    cost = dest / "figures/cost-accuracy-choice.svg"
    assert reliability.is_file()
    assert not (dest / "figures/risk-coverage-choice.svg").exists()
    assert cost.is_file()
    assert "L1" not in reliability.read_text(encoding="utf-8")
    assert "L1" in cost.read_text(encoding="utf-8")
    calib = text.split("#### 較正", maxsplit=1)[1].split("#### コスト", maxsplit=1)[0]
    assert "| L1 |" not in calib
    assert "top1" in text
    assert "error_rate" in text
    assert "n_primary" in text
    assert "ECE" in text or "ece" in text
    assert "brier" in text
    assert "signal_auroc" not in text
    assert "mean_probability" in text
    assert "mean_confidence" not in text
    assert "tokens_per_1000" in text
    _scan_public([written.markdown, *written.figures])


def _score_logs() -> list[RequestLog]:
    # gold 順位 1,2,3,4 / score 0.1,2.0,1.0,3.0 → Spearman 0.8
    pairs = ((0, 0.1), (1, 2.0), (2, 1.0), (3, 3.0))
    return [
        _log(case_id=f"s{i}", task="score", gold=gold, answer=answer)
        for i, (gold, answer) in enumerate(pairs)
    ]


def test_matrix_includes_error_rate_n_primary_and_spearman(tmp_path: Path) -> None:
    text = write_report(
        local_frame(_score_logs()), tmp_path / "out", n_bootstrap=N_BOOT
    ).markdown.read_text(encoding="utf-8")
    assert "error_rate" in text
    assert "n_primary" in text
    assert "spearman" in text
    assert "0.800" in text


def test_write_report_replaces_stale_figures(tmp_path: Path) -> None:
    dest = tmp_path / "results"
    stale = dest / "figures" / "reliability-score.svg"
    stale.parent.mkdir(parents=True)
    stale.write_text("<svg>old</svg>", encoding="utf-8")
    write_report(local_frame(_choice_logs()), dest, n_bootstrap=N_BOOT)
    assert not stale.exists()
    assert (dest / "figures" / "reliability-choice.svg").is_file()


def test_failed_write_keeps_existing_outputs(tmp_path: Path) -> None:
    dest = tmp_path / "results"
    written = write_report(local_frame(_choice_logs()), dest, n_bootstrap=N_BOOT)
    md = written.markdown.read_text(encoding="utf-8")
    fig = (dest / "figures" / "reliability-choice.svg").read_text(encoding="utf-8")
    with pytest.raises(ReportError, match="n_bootstrap"):
        write_report(local_frame(_choice_logs()), dest, n_bootstrap=0)
    assert written.markdown.read_text(encoding="utf-8") == md
    assert (dest / "figures" / "reliability-choice.svg").read_text(
        encoding="utf-8"
    ) == fig


def test_calibration_has_ten_bins_and_ece() -> None:
    table = calibration_table(local_frame(_choice_logs()))
    a = table.filter(pl.col("condition") == "A")
    assert a.height == ECE_BINS
    assert set(a["bin"].to_list()) == set(range(ECE_BINS))
    occupied = a.filter(pl.col("n") > 0)
    assert occupied.height == 3
    expected = (0.25 * abs(1 - 0.15)) + (0.5 * abs(0.5 - 0.23)) + (0.25 * abs(1 - 0.95))
    assert occupied["ece"][0] == pytest.approx(expected)
    assert "mean_probability" in table.columns
    assert "mean_confidence" not in table.columns


def test_risk_coverage_keeps_high_signal_first() -> None:
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                confidence=0.9,
                probabilities={"a": 0.9, "b": 0.1},
            ),
            _log(
                case_id="c1",
                task="choice",
                gold="a",
                answer="b",
                confidence=0.1,
                probabilities={"b": 0.6, "a": 0.4},
            ),
        ]
    )
    table = risk_coverage_table(logs)
    half = table.filter(pl.col("coverage") == 0.5)
    assert half.height == 1
    assert half["n_kept"][0] == 1
    assert half["accuracy"][0] == pytest.approx(1.0)
    full = table.filter(pl.col("coverage") == 1.0)
    assert full["accuracy"][0] == pytest.approx(0.5)


def test_risk_coverage_includes_missing_signal_as_lowest() -> None:
    logs = local_frame(
        [
            _log(
                case_id="c0",
                task="choice",
                gold="a",
                answer="a",
                confidence=0.9,
                probabilities={"a": 0.9, "b": 0.1},
            ),
            RequestLog.failed(
                case_id="c1",
                task="choice",
                condition="A",
                split="test",
                gold="a",
                content_hash=HASH_A,
                error="parse",
            ),
        ]
    )
    table = risk_coverage_table(logs)
    half = table.filter(pl.col("coverage") == 0.5)
    assert half["n_kept"][0] == 1
    assert half["accuracy"][0] == pytest.approx(1.0)
    full = table.filter(pl.col("coverage") == 1.0)
    assert full["n_kept"][0] == 2
    assert full["accuracy"][0] == pytest.approx(0.5)


def test_risk_coverage_tie_uses_group_expectation() -> None:
    shared = dict(task="choice", gold="a", confidence=0.5)
    first = local_frame(
        [
            _log(
                case_id="z-high",
                answer="a",
                probabilities={"a": 0.5, "b": 0.5},
                **shared,
            ),
            _log(
                case_id="a-low",
                answer="b",
                probabilities={"b": 0.5, "a": 0.5},
                **shared,
            ),
        ]
    )
    swapped = local_frame(
        [
            _log(
                case_id="a-high",
                answer="a",
                probabilities={"a": 0.5, "b": 0.5},
                **shared,
            ),
            _log(
                case_id="z-low",
                answer="b",
                probabilities={"b": 0.5, "a": 0.5},
                **shared,
            ),
        ]
    )
    for logs in (first, swapped):
        table = risk_coverage_table(logs)
        half = table.filter(pl.col("coverage") == 0.5)
        assert half["n_kept"][0] == 1
        assert half["accuracy"][0] == pytest.approx(0.5)
        full = table.filter(pl.col("coverage") == 1.0)
        assert full["accuracy"][0] == pytest.approx(0.5)


def test_published_records_are_enough(tmp_path: Path) -> None:
    published = published_frame(_choice_logs())
    assert "state_json" not in published.columns
    written = write_report(published, tmp_path / "out", n_bootstrap=N_BOOT)
    text = written.markdown.read_text(encoding="utf-8")
    assert "](figures/" in text
    _scan_public([written.markdown, *written.figures])


def test_write_leaves_handwritten_report(tmp_path: Path) -> None:
    dest = tmp_path / "results"
    dest.mkdir()
    report = dest / "report.md"
    report.write_text("手書きの報告\n", encoding="utf-8")
    write_report(local_frame(_choice_logs()), dest, n_bootstrap=N_BOOT)
    assert report.read_text(encoding="utf-8") == "手書きの報告\n"
    assert (dest / "tables.md").is_file()


def test_rejects_forbidden_token_in_markdown(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    write_report(local_frame(_choice_logs()), dest, n_bootstrap=N_BOOT)
    dirty = dest / "tables.md"
    dirty.write_text(dirty.read_text(encoding="utf-8") + "\nquery\n", encoding="utf-8")
    with pytest.raises(ReportError, match="query"):
        from jev_prompts.report.forbidden import reject_forbidden_files

        reject_forbidden_files([dirty])


def test_cli_report_writes_markdown(tmp_path: Path) -> None:
    published = tmp_path / "published.jsonl"
    dest = tmp_path / "results"
    write_published_records(published_frame(_choice_logs()), published)
    result = CliRunner().invoke(
        app,
        [
            "report",
            "--published",
            str(published),
            "--results-dir",
            str(dest),
            "--n-bootstrap",
            str(N_BOOT),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (dest / "tables.md").is_file()
    assert not (dest / "report.md").exists()
    text = (dest / "tables.md").read_text(encoding="utf-8")
    assert "](figures/reliability-choice.svg)" in text
    _scan_public([dest / "tables.md", *dest.joinpath("figures").glob("*.svg")])


def test_cli_report_without_published_exits_nonzero(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "report",
            "--published",
            str(tmp_path / "missing.jsonl"),
            "--results-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert "公開行" in (result.stdout + result.stderr)


def test_module_help_lists_report() -> None:
    env = os.environ.copy()
    env.pop("OPENROUTER_API_KEY", None)
    completed = subprocess.run(
        ["uv", "run", "python", "-m", "jev_prompts", "report", "--help"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "published" in completed.stdout


def test_handwritten_report_describes_calibration_probability() -> None:
    text = (REPO_ROOT / "results" / "report.md").read_text(encoding="utf-8")
    assert "### 2.3 モデルと実行" in text
    assert "### 2.4 指標" in text
    assert "### 4.2 採用した判定の確率の較正" in text
    assert "### 4.5 反省と限界" in text
    assert "採用したラベルの確率" in text
    assert "`round(score)` と同じ段階の確率" in text
    assert "max(p, 1 − p)" in text
    assert "LLM は自己申告の `confidence`" in text
    assert "Brier" in text
    assert "risk-coverage" not in text
    assert "初版は" not in text
    assert "全課題で 0.1 未満" not in text
    assert "confidence 0.9 は最大確率" not in text
    assert "A が 3 課題とも最小だったわけではない" in text


def test_root_readme_links_report() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "results/report.md" in readme
    assert "python -m jev_prompts report" in readme
    assert "results/README.md" not in readme
    assert "findings.md" not in readme


def test_checked_in_results_omit_forbidden_tokens() -> None:
    """生成物に本文キーが残らないこと。report.md は結果を見て書くので対象外。"""
    root = REPO_ROOT / "results"
    paths = [
        path for path in root.rglob("*") if path.is_file() and path.name != "report.md"
    ]
    assert paths
    for path in paths:
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"{path}: {token}"


def test_biome_skips_generated_figures() -> None:
    text = (REPO_ROOT / "biome.json").read_text(encoding="utf-8")
    assert "!results/figures" in text
    architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "biome ci" in architecture
