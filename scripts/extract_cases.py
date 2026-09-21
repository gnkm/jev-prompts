"""台帳抽出の薄い入口。ロジックは jev_prompts にある。"""

from jev_prompts.runners.cli import extract_command

if __name__ == "__main__":
    from typer import run as typer_run

    typer_run(extract_command)
