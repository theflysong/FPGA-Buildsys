"""Generate and execute the build task for one simulation."""

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
    filelist = relative(project, project.filelist(simulation))
    vvp_file = relative(project, simulation.vvp)
    vcd_file = relative(project, simulation.vcd)
    write_template(job_dir / "build.sh", "build.sh", executable=True,
                   header="\n".join(task_header(project)), filelist=shlex.quote(filelist),
                   vvp_file=shlex.quote(vvp_file), vcd_file=shlex.quote(vcd_file),
                   top=shlex.quote(simulation.top))


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "build", target_id, task_args, script)
