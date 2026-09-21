# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開 markdown レポートの Typer コマンド。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import httpx
import typer

from jev_prompts.clients import MissingApiKeyError
from jev_prompts.config import BOOTSTRAP_REPLICATES, RESULTS_DIR
from jev_prompts.report.a_errors import read_error_review
from jev_prompts.report.errors import ReportError
from jev_prompts.report.findings import write_findings
from jev_prompts.report.prices import (
    fetch_prices,
    read_measured_on,
    read_prices_markdown,
    write_prices,
)
from jev_prompts.report.write import write_report
from jev_prompts.runners.cli import app
from jev_prompts.runners.schema import LogSchemaError, read_published_records

PublishedPath = Annotated[Path, typer.Option("--published", help="公開行 JSONL")]
ResultsDir = Annotated[Path, typer.Option("--results-dir", help="markdown と図")]
BootstrapN = Annotated[int, typer.Option("--n-bootstrap", help="指標 CI の再標本数")]


@app.command("report")
def report_command(
    published: PublishedPath = RESULTS_DIR / "published.jsonl",
    results_dir: ResultsDir = RESULTS_DIR,
    n_bootstrap: BootstrapN = BOOTSTRAP_REPLICATES,
) -> None:
    """公開行から指標マトリクス・較正・コスト×精度の markdown を書く。"""
    if not published.is_file():
        typer.echo(f"公開行が無い: {published}", err=True)
        raise typer.Exit(code=1)
    try:
        logs = read_published_records(published)
        written = write_report(logs, results_dir, n_bootstrap=n_bootstrap)
    except (LogSchemaError, ReportError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"markdown: {written.markdown}")
    for path in written.figures:
        typer.echo(f"figure: {path}")


@app.command("prices")
def prices_command(
    results_dir: ResultsDir = RESULTS_DIR,
) -> None:
    """OpenRouter 掲載単価と測定日を results/prices.md に書く。"""
    try:
        prices = fetch_prices()
        path = write_prices(results_dir / "prices.md", prices, measured_on=date.today())
    except (
        MissingApiKeyError,
        OSError,
        ValueError,
        httpx.HTTPError,
        httpx.RequestError,
    ) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"prices: {path}")


@app.command("findings")
def findings_command(
    published: PublishedPath = RESULTS_DIR / "published.jsonl",
    results_dir: ResultsDir = RESULTS_DIR,
) -> None:
    """H1〜H4 と A の誤答内訳を findings.md に書く。本文は出さない。"""
    if not published.is_file():
        typer.echo(f"公開行が無い: {published}", err=True)
        raise typer.Exit(code=1)
    try:
        logs = read_published_records(published)
        prices_path = results_dir / "prices.md"
        if prices_path.is_file():
            prices = read_prices_markdown(prices_path)
            measured_on = read_measured_on(prices_path) or date.today()
        else:
            prices = None
            measured_on = date.today()
        review_path = results_dir / "a_error_review.jsonl"
        errors = read_error_review(review_path) if review_path.is_file() else None
        path = write_findings(
            logs,
            results_dir / "findings.md",
            prices=prices,
            measured_on=measured_on,
            errors=errors,
        )
    except (LogSchemaError, ReportError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"findings: {path}")
