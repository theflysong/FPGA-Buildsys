"""Generate and execute the implementation task for one FPGA program."""

from __future__ import annotations

from pathlib import Path
import shlex

from models import Program, Project
from util import (
    TMPFS_CHECK, add_target_argument as add_arguments,
    execute_job, program_header, relative, write_executable,
    require_fpga_build as validate,
)


def generate_script(project: Project, program: Program) -> None:
    job_dir = project.job_dir(program)
    header = program_header(project, program)
    synthesis = relative(project, program.synthesis)
    implementation = relative(project, program.implementation)
    constraints = relative(project, program.constraints)
    write_executable(job_dir / "implementation.sh", [
        *header,
        f'"$PROJECT_ROOT/{relative(project, job_dir / "synthesis.sh")}"',
        'command -v nextpnr-himbaechel >/dev/null || { printf "Missing tool: nextpnr-himbaechel\\n" >&2; exit 127; }',
        f"mkdir -p -- {shlex.quote(relative(project, program.implementation.parent))}",
        TMPFS_CHECK,
        f'log_dir=$(mktemp -d -- /dev/shm/buildsys-{project.identifier}-{program.identifier}-implementation-XXXXXX)',
        f'impl_log="$log_dir/{program.identifier}.implementation.log"',
        'printf "Implementation log: %s\\n" "$impl_log" >&2',
        f"nextpnr-himbaechel --device \"$FPGA_PART\" --json {shlex.quote(synthesis)} "
        f"-o {shlex.quote('xdc=' + constraints)} -o {shlex.quote('fasm=' + implementation)} "
        '--log "$impl_log"',
    ])


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "implementation", target_id, task_args, script)
