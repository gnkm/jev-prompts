"""測定表と図を書く薄い入口。report.md は書かない。ロジックは jev_prompts にある。"""

from jev_prompts.report.cli import report_command

if __name__ == "__main__":
    from typer import run as typer_run

    typer_run(report_command)
