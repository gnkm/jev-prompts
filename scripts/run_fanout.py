"""fan-out 別ランの薄い入口。ロジックは jev_prompts にある。"""

from jev_prompts.runners.cli import fanout_command

if __name__ == "__main__":
    from typer import run as typer_run

    typer_run(fanout_command)
