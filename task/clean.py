"""Generate and execute product cleanup without deleting auxiliary files."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import tempfile

from models import Project, Simulation
from util import (
    add_optional_target_argument as add_arguments, execute_job, relative,
    selected_targets, selected_targets as validate, task_header, write_executable,
)


def cleanup_script(project: Project, target_id: str | None, *, dist: bool,
                   temporary: bool = False) -> list[str]:
    lines = task_header(project, temporary=temporary)
    if temporary:
        lines.append("trap 'rm -f -- \"$0\"' EXIT")
        lines.append('[[ "$(stat -f -c %T /dev/shm)" == tmpfs ]] || { printf "Logs and temporary scripts require tmpfs at /dev/shm.\\n" >&2; exit 2; }')
    # Parse the complete function before executing it: cleandist can remove
    # this script and its directory without depending on later file reads.
    lines.append("cleanup() {")
    for target in selected_targets(project, target_id):
        outputs = ((target.vvp, target.vcd) if isinstance(target, Simulation) else
                   (target.synthesis, target.implementation, target.frames, target.bitstream))
        lines.append("  rm -f -- " + " ".join(shlex.quote(relative(project, path)) for path in outputs))
    if dist:
        if target_id is None:
            lines.extend([
                f"  rm -rf -- {shlex.quote(relative(project, project.aux_dir))}",
                f"  rm -f -- {shlex.quote(relative(project, project.script))}",
                "  rm -rf -- build/jobs",
            ])
        else:
            target = selected_targets(project, target_id)[0]
            aux = project.filelist(target) if isinstance(target, Simulation) else project.yosys_script(target)
            lines.extend([
                f"  rm -f -- {shlex.quote(relative(project, aux))}",
                f"  rm -rf -- {shlex.quote(relative(project, project.job_dir(target)))}",
            ])
    lines.extend(["}", "cleanup"])
    return lines


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
