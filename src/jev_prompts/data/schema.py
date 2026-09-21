"""台帳に書いてよい列と、本文として禁ずる列。"""

from typing import Final, Literal

type TaskId = Literal["choice", "score", "noul"]
type SplitId = Literal["dev", "test"]
type StratumId = Literal["random", "boundary"]

TASKS: Final[tuple[TaskId, ...]] = ("choice", "score", "noul")
SPLITS: Final[tuple[SplitId, ...]] = ("dev", "test")
STRATA: Final[tuple[StratumId, ...]] = ("random", "boundary")

LEDGER_COLUMNS: Final[tuple[str, ...]] = (
    "case_id",
    "task",
    "split",
    "gold",
    "content_hash",
    "extract_seed",
    "stratum",
)

BODY_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "text",
        "body",
        "content",
        "query",
        "message",
        "product",
        "title",
        "description",
        "state",
        "state_json",
        "question_json",
    }
)

SCORE_GOLD: Final[dict[str, int]] = {"I": 0, "C": 1, "S": 2, "E": 3}
NOUL_GOLD: Final[dict[str, str]] = {"spam": "yes", "ham": "no"}
