# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""Typer CLI: キーなし・本文なしで失敗し、help にモデル ID が出る。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from jev_prompts.config import JEV_MODEL_ID, LUNA_MODEL_ID, SONNET_MODEL_ID
from jev_prompts.report.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_help_lists_systemone_and_chat_model_ids() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    text = result.stdout.lower()
    assert "systemone" in text
    assert "chat" in text
    assert JEV_MODEL_ID in result.stdout
    assert LUNA_MODEL_ID in result.stdout
    assert SONNET_MODEL_ID in result.stdout
    assert "fetch" in text
    assert "preflight" in text
    assert "fanout" in text
    assert "report" in text


def test_module_help_subprocess() -> None:
    env = os.environ.copy()
    env.pop("OPENROUTER_API_KEY", None)
    completed = subprocess.run(
        ["uv", "run", "python", "-m", "jev_prompts", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert JEV_MODEL_ID in completed.stdout
    assert LUNA_MODEL_ID in completed.stdout
    assert SONNET_MODEL_ID in completed.stdout
    assert "systemone" in completed.stdout.lower()
    assert "chat" in completed.stdout.lower()


def test_run_without_key_exits_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "run",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--cases-dir",
            str(tmp_path / "cases"),
        ],
    )
    assert result.exit_code != 0
    assert "OPENROUTER_API_KEY" in (result.stdout + result.stderr)


def test_preflight_without_key_exits_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "preflight",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--cases-dir",
            str(tmp_path / "cases"),
        ],
    )
    assert result.exit_code != 0
    assert "OPENROUTER_API_KEY" in (result.stdout + result.stderr)


def test_fanout_without_key_exits_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "fanout",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--cases-dir",
            str(tmp_path / "cases"),
        ],
    )
    assert result.exit_code != 0


def test_fanout_mock_without_key_writes_logs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(app, ["fanout", "--mock", "--logs-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (tmp_path / "fanout-batched.jsonl").is_file()
    assert (tmp_path / "fanout-split.jsonl").is_file()
    assert "batched:" in result.stdout
    assert "tokens " in result.stdout
    assert "欠損あり" not in result.stdout


def test_run_without_bodies_exits_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    result = runner.invoke(
        app,
        [
            "run",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--cases-dir",
            str(tmp_path / "cases"),
        ],
    )
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "本文" in combined


def test_preflight_without_bodies_exits_nonzero(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    result = runner.invoke(
        app,
        [
            "preflight",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--cases-dir",
            str(tmp_path / "cases"),
        ],
    )
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "本文" in combined


def test_readme_splits_fetch_and_run() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m jev_prompts fetch" in readme
    assert "python -m jev_prompts preflight" in readme
    assert "python -m jev_prompts run" in readme
    assert "python -m jev_prompts fanout" in readme
    assert "scripts/fetch_data.py" in readme
    prep = readme.index("準備")
    run = readme.index("実行", prep)
    fetch = readme.index("jev_prompts fetch")
    assert prep < fetch
    assert "data/" in readme
    assert run > prep
