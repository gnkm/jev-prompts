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
    assert "](figures/reliability-choice.svg)" in text
    assert "](figures/cost-accuracy-choice.svg)" in text
    assert (dest / "figures/reliability-choice.svg").is_file()
    assert (dest / "figures/cost-accuracy-choice.svg").is_file()
    assert "top1" in text
    assert "error_rate" in text
    assert "n_primary" in text
    assert "ECE" in text or "ece" in text
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


def test_calibration_has_ten_bins_and_ece() -> None:
    table = calibration_table(local_frame(_choice_logs()))
    a = table.filter(pl.col("condition") == "A")
    assert a.height == ECE_BINS
    assert set(a["bin"].to_list()) == set(range(ECE_BINS))
    occupied = a.filter(pl.col("n") > 0)
    assert occupied.height == 3
    expected = (0.25 * abs(1 - 0.15)) + (0.5 * abs(0.5 - 0.23)) + (0.25 * abs(1 - 0.95))
    assert occupied["ece"][0] == pytest.approx(expected)


def test_published_records_are_enough(tmp_path: Path) -> None:
    published = published_frame(_choice_logs())
    assert "state_json" not in published.columns
    written = write_report(published, tmp_path / "out", n_bootstrap=N_BOOT)
    text = written.markdown.read_text(encoding="utf-8")
    assert "](figures/" in text
    _scan_public([written.markdown, *written.figures])


def test_rejects_forbidden_token_in_markdown(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    write_report(local_frame(_choice_logs()), dest, n_bootstrap=N_BOOT)
    dirty = dest / "report.md"
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
    assert (dest / "report.md").is_file()
    text = (dest / "report.md").read_text(encoding="utf-8")
    assert "](figures/reliability-choice.svg)" in text
    _scan_public([dest / "report.md", *dest.joinpath("figures").glob("*.svg")])


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


def test_root_readme_links_results_readme() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "results/README.md" in readme
    assert "python -m jev_prompts report" in readme
    assert "scripts/write_report.py" in readme


def test_results_readme_mentions_measurements() -> None:
    text = (REPO_ROOT / "results/README.md").read_text(encoding="utf-8")
    assert "測定値" in text
    assert "report.md" in text
    assert "query" in text
    assert "state_json" in text
