# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""Xenon は現行動で通り、閾値超えのブロックでは落ちる。"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _xenon_cfg() -> dict[str, object]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["xenon"]


def _run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", "scripts/check_complexity.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


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


def test_readme_and_ci_name_xenon_thresholds() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    cfg = _xenon_cfg()
    assert "xenon" in readme.lower()
    assert "radon" in readme.lower()
    assert "xenon" in workflow
    assert str(cfg["max_absolute"]) in readme
    assert "[tool.xenon]" in pyproject
    assert "[tool.radon]" in pyproject


def test_xenon_fails_when_block_exceeds_threshold(tmp_path: Path) -> None:
    cfg = _xenon_cfg()
    target = tmp_path / "too_complex.py"
    target.write_text(_over_threshold_source(), encoding="utf-8")
    result = subprocess.run(
        [
            "uv",
            "run",
            "xenon",
            "--max-absolute",
            str(cfg["max_absolute"]),
            "--max-modules",
            str(cfg["max_modules"]),
            "--max-average",
            str(cfg["max_average"]),
            str(target),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "too_complex" in combined
