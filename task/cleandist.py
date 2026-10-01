"""Generate and execute product, auxiliary file, and task script cleanup."""

from __future__ import annotations

from pathlib import Path

from models import Project
from util import add_optional_target_argument as add_arguments, execute_job, selected_targets as validate, write_executable
from .clean import cleanup_script, generate_cleanup_script


def generate_script(project: Project, target_id: str | None) -> None:
    directory = project.root / "build" / "jobs" / (target_id or "_project")
    write_executable(directory / "cleandist.sh", cleanup_script(project, target_id, dist=True))


def prepare_script(project: Project, target_id: str | None) -> Path:
    return generate_cleanup_script(project, target_id, dist=True)


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "cleandist", target_id, task_args, script)
