# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""境界フラグ付きプールと台帳抽出。"""

from pathlib import Path

import polars as pl

from jev_prompts.data import ExtractConfig, build_pool, extract_ledgers, is_boundary
from jev_prompts.data.extract import extract_cases
from jev_prompts.data.fetch import fetch_datasets
from jev_prompts.data.ledger import read_ledger
from jev_prompts.data.schema import BODY_COLUMNS
from test_fetch import (
    FakeTransport,
    _banking77_csv,
    _parquet_bytes,
    _sms_zip,
    _url_ending,
)


def test_is_boundary_by_task() -> None:
    assert is_boundary("choice", "transaction_fee_charged")
    assert not is_boundary("choice", "card_arrival")
    assert is_boundary("score", "S")
    assert not is_boundary("score", "E")
    assert is_boundary("noul", "ham")
    assert not is_boundary("noul", "spam")


def test_build_pool_sets_boundary_and_keeps_body_for_hash() -> None:
    records = {
        "train:0": {
            "source_id": "train:0",
            "text": "fee charged",
            "gold": "transaction_fee_charged",
        },
        "train:1": {
            "source_id": "train:1",
            "text": "where is card",
            "gold": "card_arrival",
        },
    }
    pool = build_pool("choice", records)
    assert pool.height == 2
    flags = dict(
        zip(pool["source_id"].to_list(), pool["boundary"].to_list(), strict=True)
    )
    assert flags["train:0"] is True
    assert flags["train:1"] is False
    assert "text" in pool.columns


def _extract_payloads() -> dict[str, bytes]:
    us_extra = pl.DataFrame(
        {
            "example_id": [10, 12],
            "query": ["running shoes", "office chair"],
            "product_id": ["p1", "p3"],
            "product_locale": ["us", "us"],
            "esci_label": ["S", "E"],
        }
    )
    products_extra = pl.DataFrame(
        {
            "product_id": ["p1", "p3"],
            "product_locale": ["us", "us"],
            "product_title": ["Trail runner", "Desk chair"],
            "product_description": ["Light trail shoe", "Mesh back"],
        }
    )
    return {
        _url_ending("train.csv"): _banking77_csv(
            ("I want my card", "card_arrival"),
            ("What is the fee", "transaction_fee_charged"),
        ),
        _url_ending("test.csv"): _banking77_csv(("Where is my card", "card_arrival")),
        _url_ending("examples.parquet"): _parquet_bytes(us_extra),
        _url_ending("products.parquet"): _parquet_bytes(products_extra),
        _url_ending("sms+spam+collection.zip"): _sms_zip(
            ("ham", "see you at 7"),
            ("spam", "WIN a prize now"),
        ),
    }


def test_extract_ledgers_writes_three_tasks(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    cases_root = tmp_path / "cases"
    fetch_datasets(raw_root, transport=FakeTransport(_extract_payloads()))
    config = ExtractConfig(seed=20260921, n_random=1, n_boundary=1, n_dev=1, n_test=1)
    paths = extract_ledgers(raw_root, cases_root, config=config)
    assert [path.name for path in paths] == [
        "choice.jsonl",
        "score.jsonl",
        "noul.jsonl",
    ]
    for path in paths:
        frame = read_ledger(path)
        assert frame.height == 2
        assert not (set(frame.columns) & BODY_COLUMNS)
        assert set(frame["split"].to_list()) == {"dev", "test"}


def test_extract_cases_from_pool_omits_body() -> None:
    records = {}
    for index in range(8):
        gold = "transaction_fee_charged" if index < 4 else "card_arrival"
        records[f"id{index}"] = {
            "source_id": f"id{index}",
            "text": f"text {index}",
            "gold": gold,
        }
    pool = build_pool("choice", records)
    config = ExtractConfig(seed=7, n_random=4, n_boundary=4, n_dev=3, n_test=5)
    frame = extract_cases(pool, task="choice", config=config)
    assert frame.height == 8
    assert not (set(frame.columns) & BODY_COLUMNS)
