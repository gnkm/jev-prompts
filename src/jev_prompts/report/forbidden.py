# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開物に置いてはいけない本文キー。"""

from collections.abc import Iterable
from pathlib import Path
from typing import Final

from jev_prompts.report.errors import ReportError

FORBIDDEN_TOKENS: Final[tuple[str, ...]] = ("query", "message", "state_json")


def reject_forbidden_text(text: str, *, source: str) -> None:
    found = [token for token in FORBIDDEN_TOKENS if token in text]
    if found:
        joined = ", ".join(found)
        raise ReportError(f"公開物に本文キーを書いてはいけない ({source}): {joined}")


def reject_forbidden_files(paths: Iterable[Path]) -> None:
    for path in paths:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="ignore")
        reject_forbidden_text(text, source=str(path))
