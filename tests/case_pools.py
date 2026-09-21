"""テスト用の合成プール。合成本文は実行時だけ作り、リポジトリには置かない。"""

import polars as pl


def choice_pool() -> pl.DataFrame:
    intents = ("card_payment_fee_charged", "transaction_fee_charged")
    rows: list[dict[str, object]] = []
    for index in range(8):
        intent = intents[index % 2]
        rows.append(
            {
                "source_id": f"c{index:02d}",
                "gold": intent,
                "boundary": True,
                "text": f"synthetic choice boundary {index:02d} {intent}",
            }
        )
    for index in range(8, 16):
        intent = intents[index % 2]
        rows.append(
            {
                "source_id": f"c{index:02d}",
                "gold": intent,
                "boundary": False,
                "text": f"synthetic choice random {index:02d} {intent}",
            }
        )
    return pl.DataFrame(rows)


def score_pool() -> pl.DataFrame:
    labels = ("S", "C")
    rows: list[dict[str, object]] = []
    for index in range(8):
        gold = labels[index % 2]
        rows.append(
            {
                "source_id": f"s{index:02d}",
                "gold": gold,
                "boundary": True,
                "query": "synthetic running shoes",
                "title": f"synthetic {gold} title {index:02d}",
                "description": f"synthetic {gold} description {index:02d}",
            }
        )
    for index in range(8, 16):
        gold = labels[index % 2]
        rows.append(
            {
                "source_id": f"s{index:02d}",
                "gold": gold,
                "boundary": False,
                "query": "synthetic running shoes",
                "title": f"synthetic {gold} title {index:02d}",
                "description": f"synthetic {gold} description {index:02d}",
            }
        )
    return pl.DataFrame(rows)


def noul_pool() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for index in range(8):
        rows.append(
            {
                "source_id": f"n{index:02d}",
                "gold": "ham",
                "boundary": True,
                "message": f"synthetic ham notification {index:02d}",
            }
        )
    for index in range(8, 16):
        rows.append(
            {
                "source_id": f"n{index:02d}",
                "gold": "spam",
                "boundary": False,
                "message": f"synthetic spam offer {index:02d}",
            }
        )
    return pl.DataFrame(rows)


def load_pool(task: str) -> pl.DataFrame:
    builders = {"choice": choice_pool, "score": score_pool, "noul": noul_pool}
    try:
        return builders[task]()
    except KeyError as exc:
        raise ValueError(f"未知の課題: {task}") from exc
