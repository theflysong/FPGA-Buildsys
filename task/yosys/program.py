"""Generate and execute the program task for one FPGA program."""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
from artifacts import shell_report, target_artifacts

from models import ProgrammingTarget, Project
from util import (
    execute_job, relative, task_header, toolchain_header, write_template,
    selected_toolchain_header,
    require_program as validate,
)


def generate_script(project: Project, program: ProgrammingTarget) -> None:
    job_dir = project.job_dir(program)
    header = [*task_header(project), *selected_toolchain_header("yosys"),
              *toolchain_header(program.toolchain_roots)]
    bitstream = relative(project, program.bitstream)
    write_template(job_dir / "program.sh", "program.sh", executable=True,
                   header="\n".join(header), program_id=shlex.quote(program.identifier),
                   bitstream=shlex.quote(bitstream), report=shell_report(project, target_artifacts(program)))


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "program", target_id, task_args, script)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target_id")
    parser.add_argument("--protocol", required=True, help="openFPGALoader cable identifier")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--busdev-num", help="USB bus:device")
    selection.add_argument("--ftdi-serial", help="FTDI adapter serial number")


def script_arguments(arguments: argparse.Namespace) -> tuple[str, ...]:
    result = ["--protocol", arguments.protocol]
    if arguments.busdev_num is not None:
        result.extend(("--busdev-num", arguments.busdev_num))
    if arguments.ftdi_serial is not None:
        result.extend(("--ftdi-serial", arguments.ftdi_serial))
    return tuple(result)
