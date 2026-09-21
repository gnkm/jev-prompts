# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""Typer の入口。ロジックは runners / data に置き、ここは薄い。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

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
from jev_prompts.data.fetch import FetchError, fetch_and_verify
from jev_prompts.runners.experiment import run_experiment
from jev_prompts.runners.fanout import FanoutError, run_fanout, write_fanout_results
from jev_prompts.runners.payload import MissingBodyError, load_run_cases
from jev_prompts.runners.preflight import (
    PreflightError,
    read_repeats,
    require_api_key,
    run_preflight,
    write_preflight_report,
)
from jev_prompts.runners.schema import write_local_logs, write_published_records

APP_HELP = f"""Jev プロンプト実験の CLI。

準備: fetch（配布元から data/raw へ取得し、台帳ハッシュと照合する）
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


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _guard_execution() -> None:
    try:
        require_api_key()
    except MissingApiKeyError as exc:
        _fail(str(exc))


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


@app.command("preflight")
def preflight_command(
    raw_dir: RawDir = RAW_DIR,
    cases_dir: CasesDir = CASES_DIR,
    logs_dir: Annotated[
        Path, typer.Option("--logs-dir", help="判定の書き出し先")
    ] = LOCAL_LOGS_DIR,
) -> None:
    """実行前: 決定性・トークン・モデル版を確認する。本文とキーが要る。"""
    _guard_execution()
    try:
        report = run_preflight(raw_dir, cases_dir)
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
    logs_dir: Annotated[
        Path, typer.Option("--logs-dir", help="再集計用ローカルログ")
    ] = LOCAL_LOGS_DIR,
    results_dir: Annotated[
        Path, typer.Option("--results-dir", help="公開用 results")
    ] = RESULTS_DIR,
) -> None:
    """本ラン: ケースごとに全条件を連続実行する。fan-out は含めない。"""
    _guard_execution()
    try:
        pairs = load_run_cases(raw_dir, cases_dir)
    except (MissingBodyError, FetchError) as exc:
        _fail(str(exc))
    from jev_prompts.runners.execute import execute_for_experiment, repeating_execute

    try:
        repeats = read_repeats(logs_dir / "preflight.json")
    except PreflightError as exc:
        _fail(str(exc))
    cases = [case for case, _record in pairs]
    records = {case.case_id: record for case, record in pairs}
    with OpenRouterClient() as client:
        execute = repeating_execute(execute_for_experiment(client, records), repeats)
        local, published = run_experiment(cases, execute)
    logs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    write_local_logs(local, logs_dir / "request_log.jsonl")
    write_published_records(published, results_dir / "published.jsonl")
    typer.echo(f"本ラン {local.height} 行（{repeats} 回平均）")
    typer.echo(f"ローカルログ: {logs_dir / 'request_log.jsonl'}")
    typer.echo(f"公開行: {results_dir / 'published.jsonl'}")


@app.command("fanout")
def fanout_command(
    raw_dir: RawDir = RAW_DIR,
    cases_dir: CasesDir = CASES_DIR,
    logs_dir: Annotated[
        Path, typer.Option("--logs-dir", help="fan-out 測定の書き出し先")
    ] = LOCAL_LOGS_DIR,
) -> None:
    """fan-out 別ラン: A の質問を 1 回にまとめる / 分割する。精度比較には入れない。"""
    _guard_execution()
    try:
        pairs = load_run_cases(raw_dir, cases_dir)
        with OpenRouterClient() as client:
            results = run_fanout(client, pairs)
    except (
        MissingApiKeyError,
        MissingBodyError,
        FetchError,
        FanoutError,
    ) as exc:
        _fail(str(exc))
    path = logs_dir / "fanout.jsonl"
    write_fanout_results(results, path)
    agreed = sum(item.agreed for item in results)
    compared = sum(item.compared for item in results)
    batched_ms = sum(item.batched_ms for item in results)
    split_ms = sum(item.split_ms for item in results)
    typer.echo(f"fan-out {len(results)} ケース")
    typer.echo(f"答えの一致: {agreed} / {compared}")
    typer.echo(f"batched 遅延合計: {batched_ms:.1f} ms")
    typer.echo(f"split 遅延合計: {split_ms:.1f} ms")
    batched_tokens = [
        item.batched_tokens for item in results if item.batched_tokens is not None
    ]
    split_tokens = [
        item.split_tokens for item in results if item.split_tokens is not None
    ]
    if batched_tokens:
        typer.echo(f"batched トークン合計: {sum(batched_tokens)}")
    if split_tokens:
        typer.echo(f"split トークン合計: {sum(split_tokens)}")
    typer.echo(f"測定: {path}")


def main() -> None:
    app()
