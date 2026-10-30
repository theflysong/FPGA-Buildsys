"""Generate and execute the run task for one simulation."""

from __future__ import annotations

from pathlib import Path
import shlex

from models import Project, Simulation
from util import (
    add_target_argument as add_arguments, execute_job, relative,
    task_header, write_template,
    require_simulation as validate,
)


def generate_script(project: Project, simulation: Simulation) -> None:
    job_dir = project.job_dir(simulation)
    vvp_file = relative(project, simulation.vvp)
    write_template(job_dir / "simulate.sh", "simulate.sh", executable=True,
                   header="\n".join(task_header(project)),
                   build_script=shlex.quote(relative(project, job_dir / "build.sh")),
                   vvp_file=shlex.quote(vvp_file))


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "simulate", target_id, task_args, script)
