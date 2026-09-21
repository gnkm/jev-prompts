# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""レイヤ契約どおりの import は通り、逆向きは lint-imports で落ちる。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LAYERS = (
    "jev_prompts.report",
    "jev_prompts.stats",
    "jev_prompts.metrics",
    "jev_prompts.runners",
    "jev_prompts.prompts",
    "jev_prompts.clients",
    "jev_prompts.data",
    "jev_prompts.config",
)


def _lint_imports(
    *,
    config: Path,
    pythonpath: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [
            "uv",
            "run",
            "lint-imports",
            "--no-cache",
            "--config",
            str(config),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _copied_project(tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    shutil.copytree(ROOT / "src" / "jev_prompts", dest / "src" / "jev_prompts")
    shutil.copy2(ROOT / "pyproject.toml", dest / "pyproject.toml")
    return dest


def _append(path: Path, extra: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")


def test_layer_packages_import() -> None:
    for name in LAYERS:
        __import__(name)


def test_lint_imports_passes_on_current_graph() -> None:
    result = _lint_imports(config=ROOT / "pyproject.toml")
    assert result.returncode == 0, result.stdout + result.stderr


def test_legal_downstream_import_passes(tmp_path: Path) -> None:
    project = _copied_project(tmp_path)
    _append(
        project / "src/jev_prompts/report/__init__.py",
        "\nimport jev_prompts.config as _config  # 契約どおり: report → config\n",
    )
    result = _lint_imports(
        config=project / "pyproject.toml",
        pythonpath=project / "src",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runners_must_not_import_report(tmp_path: Path) -> None:
    project = _copied_project(tmp_path)
    _append(
        project / "src/jev_prompts/runners/__init__.py",
        "\nimport jev_prompts.report as _report  # 逆向き: runners → report\n",
    )
    result = _lint_imports(
        config=project / "pyproject.toml",
        pythonpath=project / "src",
    )
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "jev_prompts.runners" in combined
    assert "jev_prompts.report" in combined
