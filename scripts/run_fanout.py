# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""A の質問をまとめて 1 回 vs 分割 n 回。精度比較の本ランには混ぜない。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import typer

from jev_prompts.runners import (
    RequestLog,
    RunCase,
    run_fanout_pair,
)

DEFAULT_LOG_DIR = Path("data/logs")

MOCK_QUESTIONS = {
    "intent": {"type": "choice", "instructions": "intent?"},
    "dept": {"type": "choice", "instructions": "dept?"},
}

MOCK_CASE = RunCase(
    case_id="choice:mock",
    task="choice",
    split="test",
    gold="ham",
    content_hash="a" * 64,
)


def _mock_execute(
    case: RunCase, questions: Mapping[str, Mapping[str, Any]]
) -> RequestLog:
    qids = list(questions)
    if len(qids) == 1:
        answer: str | dict[str, str] = f"ans-{qids[0]}"
    else:
        answer = {qid: f"ans-{qid}" for qid in qids}
    n = len(questions)
    return RequestLog(
        case_id=case.case_id,
        task=case.task,
        condition="A",
        split=case.split,
        probabilities={"ham": 0.7, "spam": 0.3},
        gold=case.gold,
        content_hash=case.content_hash,
        question_json=dict(questions),
        answer=answer if isinstance(answer, str) else json.dumps(answer),
        usage_tokens=10 if n > 1 else 8,
        latency_ms=5.0 if n > 1 else 4.0,
    )


def main(
    log_dir: Annotated[
        Path, typer.Option(help="2 経路のローカルログを書くディレクトリ")
    ] = DEFAULT_LOG_DIR,
    mock: Annotated[
        bool,
        typer.Option(help="ライブ API を使わずモックで 2 経路のログを書く"),
    ] = True,
) -> None:
    if not mock:
        typer.echo("ライブ API の fan-out は未配線。--mock を使う。", err=True)
        raise typer.Exit(code=1)
    _batched, _split, comparison, batched_path, split_path = run_fanout_pair(
        (MOCK_CASE,),
        MOCK_QUESTIONS,
        _mock_execute,
        log_dir=log_dir,
    )
    typer.echo(f"batched: {batched_path}")
    typer.echo(f"split: {split_path}")
    typer.echo(
        "tokens "
        f"{comparison.batched_usage_tokens} vs {comparison.split_usage_tokens}; "
        "latency_ms "
        f"{comparison.batched_latency_ms} vs {comparison.split_latency_ms}; "
        f"match_rate {comparison.match_rate} "
        f"({comparison.matched}/{comparison.compared})"
    )


if __name__ == "__main__":
    typer.run(main)
