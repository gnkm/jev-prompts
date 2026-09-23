# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""Xenon は現行動で通り、閾値超えのブロックでは落ちる。"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _xenon_cfg() -> dict[str, object]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["xenon"]


def _run_check(script: Path | None = None) -> subprocess.CompletedProcess[str]:
    # CI と同じラッパー。script を渡すと、そのコピーの ROOT（親の親）を対象にする。
    target = "scripts/check_complexity.py" if script is None else str(script)
    return subprocess.run(
        ["uv", "run", "python", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _copied_project(tmp_path: Path) -> Path:
    dest = tmp_path / "project"
    names = [str(path) for path in _xenon_cfg()["paths"]]
    if "scripts" not in names:
        names.append("scripts")
    for name in names:
        shutil.copytree(ROOT / name, dest / name)
    shutil.copy2(ROOT / "pyproject.toml", dest / "pyproject.toml")
    return dest


def _over_threshold_source() -> str:
    # CC は分岐ごとに +1。D 以上（21+）で max-absolute C を超える。
    lines = ["def too_complex(x: int) -> int:"]
    for i in range(25):
        lines.append(f"    if x == {i}:")
        lines.append(f"        return {i}")
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


def test_xenon_passes_on_current_tree() -> None:
    result = _run_check()
    assert result.returncode == 0, result.stdout + result.stderr


def test_architecture_and_ci_name_xenon_thresholds() -> None:
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    cfg = _xenon_cfg()
    assert "xenon" in architecture.lower()
    assert "radon" in architecture.lower()
    assert "max_absolute" in architecture
    assert "xenon" in workflow
    assert str(cfg["max_absolute"]) in architecture
    assert "[tool.xenon]" in pyproject
    assert "[tool.radon]" in pyproject


def test_xenon_fails_when_block_exceeds_threshold(tmp_path: Path) -> None:
    project = _copied_project(tmp_path)
    paths = [str(path) for path in _xenon_cfg()["paths"]]
    assert paths, "[tool.xenon].paths が空"
    (project / paths[0] / "too_complex.py").write_text(
        _over_threshold_source(),
        encoding="utf-8",
    )
    result = _run_check(script=project / "scripts" / "check_complexity.py")
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "too_complex" in combined
