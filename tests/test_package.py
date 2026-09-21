# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""パッケージと実行時依存が import できること。"""

import polars as pl
import typer

import jev_prompts


def test_package_and_runtime_dependencies_import() -> None:
    assert jev_prompts.__version__ == "0.1.0"
    assert pl.__version__
    assert typer.__version__
