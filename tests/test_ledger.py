"""ケース台帳: 本文なしで読め、本文列を書くと失敗する。"""

from pathlib import Path

import polars as pl
import pytest

from jev_prompts.data import (
    LEDGER_COLUMNS,
    LedgerSchemaError,
    read_ledger,
    write_ledger,
)
from jev_prompts.data.schema import BODY_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "case_id": "choice:c00",
        "task": "choice",
        "split": "dev",
        "gold": "card_payment_fee_charged",
        "content_hash": "a" * 64,
        "extract_seed": 20260921,
        "stratum": "random",
    }
    row.update(overrides)
    return row


def test_read_ledger_without_body(tmp_path: Path) -> None:
    path = tmp_path / "choice.jsonl"
    write_ledger(pl.DataFrame([_valid_row()]), path)
    df = read_ledger(path)
    assert df.height == 1
    assert df["case_id"].to_list() == ["choice:c00"]
    assert set(df.columns) == set(LEDGER_COLUMNS)
    assert not (set(df.columns) & BODY_COLUMNS)


@pytest.mark.parametrize("body_col", sorted(BODY_COLUMNS))
def test_write_rejects_body_fields(tmp_path: Path, body_col: str) -> None:
    df = pl.DataFrame([{**_valid_row(), body_col: "本文を台帳に書いてはいけない"}])
    with pytest.raises(LedgerSchemaError, match="本文フィールド"):
        write_ledger(df, tmp_path / "bad.jsonl")


def test_read_rejects_body_fields(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        '{"case_id":"choice:c00","task":"choice","split":"dev",'
        '"gold":"x","content_hash":"' + "a" * 64 + '",'
        '"extract_seed":1,"stratum":"random","text":"secret"}\n',
        encoding="utf-8",
    )
    with pytest.raises(LedgerSchemaError, match="本文フィールド"):
        read_ledger(path)


def test_tracked_ledgers_have_no_body_fields() -> None:
    cases_dir = REPO_ROOT / "data" / "cases"
    ledgers = sorted(cases_dir.glob("*.jsonl"))
    for path in ledgers:
        df = read_ledger(path)
        assert not (set(df.columns) & BODY_COLUMNS)


def test_gitignore_excludes_data_raw() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/raw/" in gitignore


def test_readme_says_body_is_not_bundled_and_fetch_is_later() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "本文は同梱しない" in readme
    assert "fetch は後続" in readme
