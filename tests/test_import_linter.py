# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""レイヤ契約どおりの import は通り、逆向きは lint-imports で落ちる。"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_INIT = ROOT / "src/jev_prompts/report/__init__.py"
RUNNERS_INIT = ROOT / "src/jev_prompts/runners/__init__.py"

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


def _lint_imports() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "lint-imports", "--no-cache"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@contextmanager
def _append(path: Path, extra: str) -> Iterator[None]:
    original = path.read_text(encoding="utf-8")
    path.write_text(original + extra, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def test_layer_packages_import() -> None:
    for name in LAYERS:
        __import__(name)


def test_lint_imports_passes_on_current_graph() -> None:
    result = _lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr


def test_legal_downstream_import_passes() -> None:
    extra = "\nimport jev_prompts.config as _config  # 契約どおり: report → config\n"
    with _append(REPORT_INIT, extra):
        result = _lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr


def test_runners_must_not_import_report() -> None:
    extra = "\nimport jev_prompts.report as _report  # 逆向き: runners → report\n"
    with _append(RUNNERS_INIT, extra):
        result = _lint_imports()
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "jev_prompts.runners" in combined
    assert "jev_prompts.report" in combined
