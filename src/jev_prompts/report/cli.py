# SPDX-FileCopyrightText: 2026 gnkm
#
# SPDX-License-Identifier: MIT

"""公開 markdown レポートの Typer コマンド。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from jev_prompts.config import BOOTSTRAP_REPLICATES, RESULTS_DIR
from jev_prompts.report.errors import ReportError
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
