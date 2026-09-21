"""公開 markdown レポートの薄い入口。ロジックは jev_prompts にある。"""

from jev_prompts.report.cli import report_command

if __name__ == "__main__":
    from typer import run as typer_run

    typer_run(report_command)
