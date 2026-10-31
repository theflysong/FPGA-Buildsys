"""Generate and execute the nextpnr implementation task for one FPGA program."""

from __future__ import annotations

from pathlib import Path
import shlex
from artifacts import shell_report, target_artifacts

from models import ImplementationProgram, Project
from util import (
    add_target_argument as add_arguments,
    execute_job, program_header, relative, render_template, write_template,
    require_fpga_build as validate,
)


def generate_script(project: Project, program: ImplementationProgram) -> None:
    job_dir = project.job_dir(program)
    synthesis = relative(project, program.synthesis)
    implementation = relative(project, program.implementation)
    constraints = relative(project, program.constraints)
    write_template(
        job_dir / "implementation.sh", "yosys/implementation.sh", executable=True,
        header="\n".join(program_header(project, program)),
        synthesis_script=shlex.quote(relative(project, job_dir / "synthesis.sh")),
        output_directory=shlex.quote(relative(project, program.implementation.parent)),
        tmpfs_check=render_template("shell/tmpfs-check.sh").rstrip("\n"),
        log_directory=shlex.quote(f"/dev/shm/buildsys-{project.identifier}-{program.identifier}-implementation-XXXXXX"),
        program_id=program.identifier, synthesis=shlex.quote(synthesis),
        constraints_option=shlex.quote("xdc=" + constraints),
        implementation_option=shlex.quote("fasm=" + implementation),
        report=shell_report(project, target_artifacts(program, stage="implementation")),
    )


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "implementation", target_id, task_args, script)
