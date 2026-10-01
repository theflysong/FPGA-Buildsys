"""Generate and execute the bitstream task for one FPGA program."""

from __future__ import annotations

from pathlib import Path
import shlex

from models import Program, Project
from util import (
    add_target_argument as add_arguments,
    execute_job, program_header, relative, write_executable,
    require_fpga_build as validate,
)


def generate_script(project: Project, program: Program) -> None:
    job_dir = project.job_dir(program)
    header = program_header(project, program)
    implementation = relative(project, program.implementation)
    bitstream = relative(project, program.bitstream)
    frames = relative(project, program.frames)
    write_executable(job_dir / "bitstream.sh", [
        *header,
        f'"$PROJECT_ROOT/{relative(project, job_dir / "implementation.sh")}"',
        'command -v fasm2frames >/dev/null || { printf "Missing tool: fasm2frames\\n" >&2; exit 127; }',
        'command -v xc7frames2bit >/dev/null || { printf "Missing tool: xc7frames2bit\\n" >&2; exit 127; }',
        '[[ -f "$XRAY_DATABASE/$FPGA_PART/part.yaml" ]] || { printf "Missing FPGA part database: %s\\n" "$XRAY_DATABASE/$FPGA_PART/part.yaml" >&2; exit 2; }',
        f"mkdir -p -- {shlex.quote(relative(project, program.bitstream.parent))}",
        f"fasm2frames --db-root \"$XRAY_DATABASE\" --part \"$FPGA_PART\" {shlex.quote(implementation)} {shlex.quote(frames)}",
        f"xc7frames2bit --part_file \"$XRAY_DATABASE/$FPGA_PART/part.yaml\" --part_name \"$FPGA_PART\" "
        f"--frm_file {shlex.quote(frames)} --output_file {shlex.quote(bitstream)}",
    ])


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "bitstream", target_id, task_args, script)
