"""課題あたりランダム + 境界を切り出し、gold で層化した split を振る。"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import polars as pl

from jev_prompts.data.hashutil import content_hash
from jev_prompts.data.ledger import validate_ledger
from jev_prompts.data.schema import NOUL_GOLD, SCORE_GOLD, TASKS, TaskId


@dataclass(frozen=True, slots=True)
class ExtractConfig:
    seed: int
    n_random: int = 50
    n_boundary: int = 50
    n_dev: int = 40
    n_test: int = 60

    def __post_init__(self) -> None:
        for name, value in (
            ("n_random", self.n_random),
            ("n_boundary", self.n_boundary),
            ("n_dev", self.n_dev),
            ("n_test", self.n_test),
        ):
            if value < 1:
                raise ValueError(f"{name} は 1 以上: {value}")
        extracted = self.n_random + self.n_boundary
        split_total = self.n_dev + self.n_test
        if extracted != split_total:
            raise ValueError(
                f"n_random+n_boundary ({extracted}) と "
                f"n_dev+n_test ({split_total}) が一致しない"
            )


def map_gold(task: TaskId, raw: Any) -> int | str:
    if task == "choice":
        label = str(raw)
        if not label:
            raise ValueError("choice の gold が空")
        return label
    if task == "score":
        if isinstance(raw, bool) or raw is None:
            raise ValueError(f"score の gold が不正: {raw!r}")
        if isinstance(raw, int) and raw in SCORE_GOLD.values():
            return raw
        key = str(raw)
        if key in SCORE_GOLD:
            return SCORE_GOLD[key]
        if key.isdigit() and int(key) in SCORE_GOLD.values():
            return int(key)
        raise ValueError(f"score の gold が不正: {raw!r}")
    if task == "noul":
        key = str(raw)
        if key in NOUL_GOLD:
            return NOUL_GOLD[key]
        if key in NOUL_GOLD.values():
            return key
        raise ValueError(f"noul の gold が不正: {raw!r}")
    raise ValueError(f"未知の課題: {task}")


def _require_task(task: str) -> TaskId:
    if task not in TASKS:
        raise ValueError(f"未知の課題: {task}")
    return task


def _assign_splits(
    records: list[dict[str, Any]],
    n_dev: int,
    n_test: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    total = len(records)
    if total != n_dev + n_test:
        raise ValueError(
            f"抽出件数 {total} が n_dev+n_test={n_dev + n_test} と一致しない"
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["gold"])].append(record)

    for key in grouped:
        rng.shuffle(grouped[key])

    classes = sorted(grouped, key=lambda k: (-len(grouped[k]), k))
    max_both = min(n_dev, n_test)
    reserved_dev: list[dict[str, Any]] = []
    reserved_test: list[dict[str, Any]] = []
    leftovers: list[dict[str, Any]] = []
    both_count = 0
    for key in classes:
        items = grouped[key]
        if len(items) >= 2 and both_count < max_both:
            reserved_dev.append(items[0])
            reserved_test.append(items[1])
            leftovers.extend(items[2:])
            both_count += 1
        else:
            leftovers.extend(items)

    rng.shuffle(leftovers)
    need_dev = n_dev - len(reserved_dev)
    need_test = n_test - len(reserved_test)
    if need_dev + need_test != len(leftovers):
        raise ValueError("層化 split の余り件数と不足枠が一致しない")

    in_dev = {str(item["gold"]) for item in reserved_dev}
    in_test = {str(item["gold"]) for item in reserved_test}
    remaining: list[dict[str, Any]] = []
    for item in leftovers:
        gold = str(item["gold"])
        if gold not in in_dev and need_dev > 0:
            reserved_dev.append(item)
            in_dev.add(gold)
            need_dev -= 1
        elif gold not in in_test and need_test > 0:
            reserved_test.append(item)
            in_test.add(gold)
            need_test -= 1
        else:
            remaining.append(item)

    for item in remaining:
        if need_dev > 0:
            reserved_dev.append(item)
            need_dev -= 1
        else:
            reserved_test.append(item)
            need_test -= 1

    assigned: list[dict[str, Any]] = []
    for item in reserved_dev:
        assigned.append({**item, "split": "dev"})
    for item in reserved_test:
        assigned.append({**item, "split": "test"})
    _require_multi_gold_in_both_splits(assigned, n_dev=n_dev, n_test=n_test)
    return assigned


def _require_multi_gold_in_both_splits(
    assigned: list[dict[str, Any]], *, n_dev: int, n_test: int
) -> None:
    """件数が 2 以上の gold は、枠が足りるとき dev/test の両方に入れる。"""
    by_gold: dict[str, list[str]] = defaultdict(list)
    for record in assigned:
        by_gold[str(record["gold"])].append(str(record["split"]))
    multi = [gold for gold, splits in by_gold.items() if len(splits) >= 2]
    if len(multi) > min(n_dev, n_test):
        return
    missing = [gold for gold in sorted(multi) if set(by_gold[gold]) != {"dev", "test"}]
    if missing:
        raise ValueError(f"gold が dev/test の両方に入っていない: {missing}")


def extract_cases(
    pool: pl.DataFrame, *, task: str, config: ExtractConfig
) -> pl.DataFrame:
    """小さなプールからケース台帳行を作る。本文列は出力に含めない。"""
    task_id = _require_task(task)
    if pool.height == 0:
        raise ValueError("抽出プールが空")
    required = {"source_id", "gold", "boundary"}
    missing = sorted(required - set(pool.columns))
    if missing:
        raise ValueError(f"プールに必須列が無い: {', '.join(missing)}")

    records = sorted(pool.to_dicts(), key=lambda r: str(r["source_id"]))
    source_ids = [str(r["source_id"]) for r in records]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source_id が重複している")
    records = _drop_duplicate_hashes(records, task_id)

    boundary = [r for r in records if bool(r["boundary"])]
    non_boundary = [r for r in records if not bool(r["boundary"])]
    if len(boundary) < config.n_boundary:
        raise ValueError(f"境界ケースが不足: {len(boundary)} < {config.n_boundary}")
    if len(non_boundary) < config.n_random:
        raise ValueError(
            f"ランダム用ケースが不足: {len(non_boundary)} < {config.n_random}"
        )

    rng = random.Random(config.seed)
    picked_boundary = rng.sample(boundary, config.n_boundary)
    picked_random = rng.sample(non_boundary, config.n_random)
    picked: list[dict[str, Any]] = []
    for record in picked_boundary:
        picked.append(
            {**record, "gold": map_gold(task_id, record["gold"]), "stratum": "boundary"}
        )
    for record in picked_random:
        picked.append(
            {**record, "gold": map_gold(task_id, record["gold"]), "stratum": "random"}
        )

    assigned = _assign_splits(picked, config.n_dev, config.n_test, rng)
    rows: list[dict[str, Any]] = []
    for record in assigned:
        source_id = str(record["source_id"])
        rows.append(
            {
                "case_id": f"{task_id}:{source_id}",
                "task": task_id,
                "split": record["split"],
                "gold": record["gold"],
                "content_hash": content_hash(task_id, record),
                "extract_seed": config.seed,
                "stratum": record["stratum"],
            }
        )

    df = pl.DataFrame(rows).sort("case_id")
    if df["content_hash"].n_unique() != df.height:
        raise ValueError("content_hash が重複している")
    validate_ledger(df)
    return df


def _drop_duplicate_hashes(
    records: list[dict[str, Any]], task_id: TaskId
) -> list[dict[str, Any]]:
    """同一本文は source_id が先の 1 件だけ残す。"""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        digest = content_hash(task_id, record)
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(record)
    return unique
