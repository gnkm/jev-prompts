# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""Typer の入口。ロジックは runners / data に置き、ここは薄い。"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import polars as pl
import typer

from jev_prompts.clients import MissingApiKeyError, OpenRouterClient
from jev_prompts.config import (
    API_KEY_ENV,
    CASES_DIR,
    JEV_MODEL_ID,
    LOCAL_LOGS_DIR,
    LUNA_MODEL_ID,
    RAW_DIR,
    RESULTS_DIR,
    SONNET_MODEL_ID,
)
from jev_prompts.data.extract import ExtractConfig
from jev_prompts.data.fetch import FetchError, fetch_and_verify
from jev_prompts.data.pools import extract_ledgers
from jev_prompts.data.schema import SPLITS, SplitId
from jev_prompts.prompts.catalog import CONDITIONS, load_bundle
from jev_prompts.runners.execute import (
    execute_for_experiment,
    execute_for_fanout,
    repeating_execute,
)
from jev_prompts.runners.experiment import (
    RunCase,
    assert_resume_matches,
    completed_pairs,
    run_experiment,
)
from jev_prompts.runners.fanout import (
    FanoutComparison,
    compare_fanout,
    run_fanout_pair,
    write_fanout_logs,
)
from jev_prompts.runners.payload import MissingBodyError, load_run_cases
from jev_prompts.runners.preflight import (
    PreflightError,
    read_repeats,
    require_api_key,
    run_preflight,
    write_preflight_report,
)
from jev_prompts.runners.schema import (
    LogSchemaError,
    RequestLog,
    local_frame,
    read_local_logs,
    to_published,
    write_local_logs,
    write_published_records,
)

APP_HELP = f"""Jev プロンプト実験の CLI。

準備: fetch（配布元から data/raw へ取得し、台帳ハッシュと照合する）
抽出: extract（raw から本文なし台帳を切る）
実行: preflight / run / fanout（data/ だけを読む。配布元には触れない）

systemone のモデル ID: {JEV_MODEL_ID}
chat のモデル ID: {LUNA_MODEL_ID} / {SONNET_MODEL_ID}

キーは {API_KEY_ENV}。本文が無ければ実行系は失敗する。
"""

app = typer.Typer(
    help=APP_HELP,
    no_args_is_help=True,
    add_completion=False,
)

RawDir = Annotated[Path, typer.Option("--raw-dir", help="配布元の展開先")]
CasesDir = Annotated[Path, typer.Option("--cases-dir", help="ケース台帳のディレクトリ")]
LogsDir = Annotated[
    Path, typer.Option("--logs-dir", "--log-dir", help="ローカルログの書き出し先")
]
SplitOpt = Annotated[
    str | None,
    typer.Option("--split", help="dev または test。省略時は両方"),
]

_MOCK_QUESTIONS = {
    "intent": {"type": "choice", "instructions": "intent?"},
    "dept": {"type": "choice", "instructions": "dept?"},
}
_MOCK_CASE = RunCase(
    case_id="choice:mock",
    task="choice",
    split="test",
    gold="ham",
    content_hash="a" * 64,
)


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _guard_execution() -> None:
    try:
        require_api_key()
    except MissingApiKeyError as exc:
        _fail(str(exc))


def _parse_split(value: str | None) -> SplitId | None:
    if value is None or value == "":
        return None
    if value not in SPLITS:
        _fail(f"未知の split: {value}")
    return value  # type: ignore[return-value]


def _existing_local(path: Path) -> pl.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return local_frame([])
    return read_local_logs(path)


@app.command("fetch")
def fetch_command(
    raw_dir: RawDir = RAW_DIR,
    cases_dir: CasesDir = CASES_DIR,
) -> None:
    """準備: 配布元から取得し、台帳の content_hash と照合する。"""
    try:
        checked = fetch_and_verify(raw_dir, cases_dir)
    except FetchError as exc:
        _fail(str(exc))
    typer.echo(f"取得完了: {raw_dir}")
    typer.echo(f"ハッシュ照合 OK ({checked} 件)")


@app.command("extract")
def extract_command(
    raw_dir: RawDir = RAW_DIR,
    cases_dir: CasesDir = CASES_DIR,
    seed: Annotated[int, typer.Option("--seed", help="抽出シード")] = 20260921,
) -> None:
    """raw から課題あたり 100 件の台帳を切る。本文は書かない。"""
    try:
        paths = extract_ledgers(raw_dir, cases_dir, config=ExtractConfig(seed=seed))
    except (FetchError, ValueError) as exc:
        _fail(str(exc))
    for path in paths:
        typer.echo(str(path))


@app.command("preflight")
def preflight_command(
    raw_dir: RawDir = RAW_DIR,
    cases_dir: CasesDir = CASES_DIR,
    logs_dir: LogsDir = LOCAL_LOGS_DIR,
    split: SplitOpt = None,
) -> None:
    """実行前: 決定性・トークン・モデル版を確認する。本文とキーが要る。"""
    _guard_execution()
    try:
        report = run_preflight(raw_dir, cases_dir, split=_parse_split(split))
    except (MissingApiKeyError, MissingBodyError, FetchError, PreflightError) as exc:
        _fail(str(exc))
    write_preflight_report(report, logs_dir / "preflight.json")
    typer.echo(f"モデル版: {report.model}")
    for check in report.token_checks:
        typer.echo(
            f"トークン {check.task}/{check.condition}: {check.tokens} / {check.limit}"
        )
    if report.deterministic:
        typer.echo("決定性: 同一入力で一致")
    else:
        typer.echo(f"決定性: 不一致のため本ランは {report.repeats} 回平均")
    typer.echo(f"本文照合: {report.bodies} 件")
    typer.echo(f"判定: {logs_dir / 'preflight.json'}")


@app.command("run")
def run_command(
    raw_dir: RawDir = RAW_DIR,
    cases_dir: CasesDir = CASES_DIR,
    logs_dir: LogsDir = LOCAL_LOGS_DIR,
    results_dir: Annotated[
        Path, typer.Option("--results-dir", help="公開用 results")
    ] = RESULTS_DIR,
    split: SplitOpt = None,
) -> None:
    """本ラン: ケースごとに全条件を連続実行する。fan-out は含めない。"""
    _guard_execution()
    try:
        pairs = load_run_cases(raw_dir, cases_dir, split=_parse_split(split))
    except (MissingBodyError, FetchError) as exc:
        _fail(str(exc))
    case_ids = [case.case_id for case, _record in pairs]
    try:
        repeats = read_repeats(logs_dir / "preflight.json", case_ids=case_ids)
    except PreflightError as exc:
        _fail(str(exc))
    cases = [case for case, _record in pairs]
    records = {case.case_id: record for case, record in pairs}
    logs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    local_path = logs_dir / "request_log.jsonl"
    published_path = results_dir / "published.jsonl"
    existing = _existing_local(local_path)
    try:
        assert_resume_matches(existing, cases)
    except LogSchemaError as exc:
        _fail(str(exc))
    skip = completed_pairs(existing)
    planned = len(cases) * len(CONDITIONS)
    collected: list[RequestLog] = []

    def on_row(log: RequestLog) -> None:
        collected.append(log)
        added = local_frame(collected)
        combined = pl.concat([existing, added]) if existing.height else added
        write_local_logs(combined, local_path)
        write_published_records(to_published(combined), published_path)
        current = existing.height + len(collected)
        if current % 10 == 0 or current == planned:
            typer.echo(f"{current}/{planned}")

    with OpenRouterClient() as client:
        execute = repeating_execute(execute_for_experiment(client, records), repeats)
        new_local, _published = run_experiment(cases, execute, skip=skip, on_row=on_row)
    if existing.height and new_local.height:
        local = pl.concat([existing, new_local])
    elif existing.height:
        local = existing
    else:
        local = new_local
    write_local_logs(local, local_path)
    write_published_records(to_published(local), published_path)
    typer.echo(f"本ラン {local.height} 行（{repeats} 回平均）")
    typer.echo(f"ローカルログ: {local_path}")
    typer.echo(f"公開行: {published_path}")


def _mock_fanout_execute(
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


def _usage_label(frame: pl.DataFrame, complete_total: int) -> str:
    if "usage_tokens" not in frame.columns:
        return "欠損あり"
    values = frame["usage_tokens"].to_list()
    if not values or any(item is None for item in values):
        return "欠損あり"
    return str(complete_total)


def _echo_fanout(
    comparison: FanoutComparison,
    batched: pl.DataFrame,
    split: pl.DataFrame,
    batched_path: Path,
    split_path: Path,
) -> None:
    typer.echo(f"batched: {batched_path}")
    typer.echo(f"split: {split_path}")
    typer.echo(
        "tokens "
        f"{_usage_label(batched, comparison.batched_usage_tokens)} vs "
        f"{_usage_label(split, comparison.split_usage_tokens)}; "
        "latency_ms "
        f"{comparison.batched_latency_ms} vs {comparison.split_latency_ms}; "
        f"match_rate {comparison.match_rate} "
        f"({comparison.matched}/{comparison.compared})"
    )


def _task_questions(task: str) -> dict[str, dict[str, Any]]:
    bundle = load_bundle(task, "A")
    if bundle.questions is None:
        raise LogSchemaError(f"{task}/A に questions が無い")
    return {str(qid): dict(item) for qid, item in bundle.questions.items()}


def _live_fanout(raw_dir: Path, cases_dir: Path, logs_dir: Path) -> None:
    pairs = load_run_cases(raw_dir, cases_dir)
    grouped: dict[str, list[tuple[RunCase, dict[str, Any]]]] = defaultdict(list)
    for case, record in pairs:
        grouped[case.task].append((case, record))
    batched_parts: list[pl.DataFrame] = []
    split_parts: list[pl.DataFrame] = []
    with OpenRouterClient() as client:
        for task, items in grouped.items():
            questions = _task_questions(task)
            cases = [case for case, _record in items]
            records = {case.case_id: record for case, record in items}
            batched, split, comparison, _b, _s = run_fanout_pair(
                cases, questions, execute_for_fanout(client, records)
            )
            batched_parts.append(batched)
            split_parts.append(split)
            typer.echo(
                f"{task}: match_rate {comparison.match_rate} "
                f"({comparison.matched}/{comparison.compared})"
            )
    batched = pl.concat(batched_parts)
    split = pl.concat(split_parts)
    batched_path, split_path = write_fanout_logs(batched, split, logs_dir)
    n_questions = max((part.height for part in split_parts), default=0)
    comparison = compare_fanout(batched, split, n_questions=n_questions)
    _echo_fanout(comparison, batched, split, batched_path, split_path)


@app.command("fanout")
def fanout_command(
    raw_dir: RawDir = RAW_DIR,
    cases_dir: CasesDir = CASES_DIR,
    logs_dir: LogsDir = LOCAL_LOGS_DIR,
    mock: Annotated[
        bool,
        typer.Option(help="ライブ API を使わずモックで 2 経路のログを書く"),
    ] = False,
) -> None:
    """fan-out 別ラン: A の質問を 1 回にまとめる / 分割する。精度比較には入れない。"""
    if mock:
        batched, split, comparison, batched_path, split_path = run_fanout_pair(
            (_MOCK_CASE,),
            _MOCK_QUESTIONS,
            _mock_fanout_execute,
            log_dir=logs_dir,
        )
        assert batched_path is not None and split_path is not None
        _echo_fanout(comparison, batched, split, batched_path, split_path)
        return
    _guard_execution()
    try:
        _live_fanout(raw_dir, cases_dir, logs_dir)
    except (
        MissingApiKeyError,
        MissingBodyError,
        FetchError,
        LogSchemaError,
    ) as exc:
        _fail(str(exc))


def main() -> None:
    app()
