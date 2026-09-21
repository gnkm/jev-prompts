# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""pyproject.toml の [tool.xenon] を正本に、Xenon 複雑度ゲートを実行する。"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def xenon_command(root: Path = ROOT) -> list[str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    cfg = data["tool"]["xenon"]
    return [
        "xenon",
        "--max-absolute",
        str(cfg["max_absolute"]),
        "--max-modules",
        str(cfg["max_modules"]),
        "--max-average",
        str(cfg["max_average"]),
        *[str(path) for path in cfg["paths"]],
    ]


def main() -> int:
    if not PYPROJECT.is_file():
        print(f"pyproject.toml が無い: {PYPROJECT}", file=sys.stderr)
        return 2
    return subprocess.call(xenon_command(), cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
