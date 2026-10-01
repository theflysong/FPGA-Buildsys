"""Generate and execute the build task for one simulation."""

from __future__ import annotations

from pathlib import Path
import shlex

from models import Project, Simulation
from util import (
    add_target_argument as add_arguments, execute_job, relative,
    task_header, write_executable,
    require_simulation as validate,
)


def generate_script(project: Project, simulation: Simulation) -> None:
    job_dir = project.job_dir(simulation)
    header = task_header(project)
    filelist = relative(project, project.filelist(simulation))
    vvp_file = relative(project, simulation.vvp)
    vcd_file = relative(project, simulation.vcd)
    build_lines = [
        *header,
        f"filelist={shlex.quote(filelist)}",
        f"vvp_file={shlex.quote(vvp_file)}",
        f"vcd_file={shlex.quote(vcd_file)}",
        'if [[ ! -f "$filelist" ]]; then',
        '  printf "Missing %s; run the Python aux command first.\\n" "$filelist" >&2',
        '  exit 2',
        'fi',
        'mkdir -p -- "$(dirname -- "$vvp_file")" "$(dirname -- "$vcd_file")"',
        f'iverilog -g2012 -Wall -s {shlex.quote(simulation.top)} -f "$filelist" "-D__VCD_FILE__=\\\"$vcd_file\\\"" -o "$vvp_file"',
    ]
    write_executable(job_dir / "build.sh", build_lines)


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "build", target_id, task_args, script)
