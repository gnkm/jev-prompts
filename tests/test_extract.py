"""同一シードでケース ID 集合が一致すること。層化 split と gold 写像。"""

from pathlib import Path

import polars as pl
import pytest

from jev_prompts.data import ExtractConfig, extract_cases, write_ledger
from jev_prompts.data.extract import map_gold
from jev_prompts.data.hashutil import content_hash
from jev_prompts.data.schema import BODY_COLUMNS

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pools"

SAMPLE = ExtractConfig(seed=20260921, n_random=4, n_boundary=4, n_dev=3, n_test=5)
FULL = ExtractConfig(seed=20260921, n_random=8, n_boundary=8, n_dev=6, n_test=10)


def load_pool(task: str) -> pl.DataFrame:
    return pl.read_ndjson(FIXTURES / f"{task}.jsonl")


@pytest.mark.parametrize("task", ["choice", "score", "noul"])
def test_same_seed_same_case_ids(task: str) -> None:
    pool = load_pool(task)
    first = extract_cases(pool, task=task, config=SAMPLE)
    second = extract_cases(pool, task=task, config=SAMPLE)
    assert sorted(first["case_id"].to_list()) == sorted(second["case_id"].to_list())
    assert first.select(sorted(first.columns)).equals(
        second.select(sorted(second.columns))
    )


@pytest.mark.parametrize("task", ["choice", "score", "noul"])
def test_extract_drops_body_and_keeps_schema(task: str) -> None:
    df = extract_cases(load_pool(task), task=task, config=SAMPLE)
    assert not (set(df.columns) & BODY_COLUMNS)
    assert df.height == SAMPLE.n_random + SAMPLE.n_boundary
    assert df.filter(pl.col("stratum") == "random").height == SAMPLE.n_random
    assert df.filter(pl.col("stratum") == "boundary").height == SAMPLE.n_boundary
    assert df.filter(pl.col("split") == "dev").height == SAMPLE.n_dev
    assert df.filter(pl.col("split") == "test").height == SAMPLE.n_test
    assert set(df["extract_seed"].to_list()) == {SAMPLE.seed}


@pytest.mark.parametrize("task", ["choice", "score", "noul"])
def test_stratified_split_puts_each_gold_in_both_splits(task: str) -> None:
    df = extract_cases(load_pool(task), task=task, config=FULL)
    golds = df["gold"].unique().to_list()
    assert golds
    for gold in golds:
        splits = set(df.filter(pl.col("gold") == gold)["split"].to_list())
        assert splits == {"dev", "test"}, gold


def test_score_and_noul_gold_mapping() -> None:
    assert map_gold("score", "I") == 0
    assert map_gold("score", "C") == 1
    assert map_gold("score", "S") == 2
    assert map_gold("score", "E") == 3
    assert map_gold("noul", "spam") == "yes"
    assert map_gold("noul", "ham") == "no"
    score = extract_cases(load_pool("score"), task="score", config=SAMPLE)
    assert set(score["gold"].to_list()) <= {1, 2}
    noul = extract_cases(load_pool("noul"), task="noul", config=SAMPLE)
    assert set(noul["gold"].to_list()) <= {"yes", "no"}


def test_content_hash_is_sha256_of_payload() -> None:
    pool = load_pool("choice")
    record = pool.to_dicts()[0]
    digest = content_hash("choice", record)
    assert len(digest) == 64
    df = extract_cases(pool, task="choice", config=SAMPLE)
    hashed_ids = {r["source_id"]: content_hash("choice", r) for r in pool.to_dicts()}
    for row in df.to_dicts():
        source_id = row["case_id"].split(":", 1)[1]
        assert row["content_hash"] == hashed_ids[source_id]


def test_write_extracted_ledger_without_body(tmp_path: Path) -> None:
    df = extract_cases(load_pool("choice"), task="choice", config=SAMPLE)
    path = tmp_path / "choice.jsonl"
    write_ledger(df, path)
    text = path.read_text(encoding="utf-8")
    assert "fixture:" not in text
    assert '"text"' not in text
