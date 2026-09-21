"""配布元から data/raw へ取得し、台帳ハッシュと照合する薄い入口。"""

from jev_prompts.runners.cli import fetch_command

if __name__ == "__main__":
    from typer import run as typer_run

    typer_run(fetch_command)
