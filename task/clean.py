"""Generate and execute product cleanup without deleting auxiliary files."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import tempfile

from models import Project
from util import (
    add_optional_target_argument as add_arguments, execute_job, relative,
    render_template, selected_targets, selected_targets as validate, task_header, write_executable,
)


def cleanup_script(project: Project, target_id: str | None, *, dist: bool,
                   temporary: bool = False) -> list[str]:
    def remove(*paths: Path, recursive: bool = False) -> str:
        return render_template("shell/remove.sh", flags="-rf" if recursive else "-f",
                               paths=" ".join(shlex.quote(relative(project, path)) for path in paths))

    outputs = "".join(remove(*target.outputs) for target in selected_targets(project, target_id))
    generated = ""
    if dist:
        if target_id is None:
            generated = "".join(remove(path, recursive=True) for path in (
                project.auxiliary_dir, project.model_dir, project.symbol_dir,
            )) + remove(project.script) + remove(project.root / "build/jobs", recursive=True)
        else:
            target = selected_targets(project, target_id)[0]
            generated = remove(target.auxiliary) + remove(project.job_dir(target), recursive=True)
    return render_template(
        "cleanup.sh", header="\n".join(task_header(project, temporary=temporary)),
        temporary_header=render_template("shell/temporary-cleanup.sh").rstrip("\n") if temporary else "",
        remove_outputs=outputs.rstrip("\n"), remove_generated=generated.rstrip("\n"),
    ).splitlines()


def generate_cleanup_script(project: Project, target_id: str | None, *, dist: bool) -> Path:
    descriptor, filename = tempfile.mkstemp(prefix="buildsys-clean-", suffix=".sh", dir="/dev/shm")
    os.close(descriptor)
    path = Path(filename)
    write_executable(path, cleanup_script(project, target_id, dist=dist, temporary=True))
    return path


def generate_script(project: Project, target_id: str | None) -> None:
    directory = project.root / "build" / "jobs" / (target_id or "_project")
    write_executable(directory / "clean.sh", cleanup_script(project, target_id, dist=False))


def prepare_script(project: Project, target_id: str | None) -> Path:
    return generate_cleanup_script(project, target_id, dist=False)


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "clean", target_id, task_args, script)
