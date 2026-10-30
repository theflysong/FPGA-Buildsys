"""Generate and execute the Project X-Ray bitstream task for one FPGA program."""

from __future__ import annotations

from pathlib import Path
import shlex

from models import Program, Project
from util import (
    add_target_argument as add_arguments,
    execute_job, program_header, relative, write_template,
    require_fpga_build as validate,
)


def generate_script(project: Project, program: Program) -> None:
    job_dir = project.job_dir(program)
    implementation = relative(project, program.implementation)
    bitstream = relative(project, program.bitstream)
    frames = relative(project, program.frames)
    write_template(
        job_dir / "bitstream.sh", "yosys/bitstream.sh", executable=True,
        header="\n".join(program_header(project, program)),
        implementation_script=shlex.quote(relative(project, job_dir / "implementation.sh")),
        output_directory=shlex.quote(relative(project, program.bitstream.parent)),
        implementation=shlex.quote(implementation), frames=shlex.quote(frames),
        bitstream=shlex.quote(bitstream),
    )


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "bitstream", target_id, task_args, script)
