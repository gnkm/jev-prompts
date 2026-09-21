"""配布元から data/raw へ取得し、台帳ハッシュと照合する薄い入口。"""

from pathlib import Path
from typing import Annotated

import typer

from jev_prompts.data.fetch import FetchError, fetch_and_verify

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_CASES_DIR = Path("data/cases")


def main(
    raw_dir: Annotated[Path, typer.Option(help="配布元の展開先")] = DEFAULT_RAW_DIR,
    cases_dir: Annotated[
        Path, typer.Option(help="ケース台帳のディレクトリ")
    ] = DEFAULT_CASES_DIR,
) -> None:
    try:
        checked = fetch_and_verify(raw_dir, cases_dir)
    except FetchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"取得完了: {raw_dir}")
    if checked == 0:
        typer.echo("台帳が無いのでハッシュ照合をスキップした")
        return
    typer.echo(f"ハッシュ照合 OK ({checked} 件)")


if __name__ == "__main__":
    typer.run(main)
