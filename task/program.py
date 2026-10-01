"""Generate and execute the program task for one FPGA program."""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex

from models import Program, Project
from util import (
    BUILDSYS_DIR, execute_job, program_header, relative, write_executable,
    require_program as validate,
)


def generate_script(project: Project, program: Program) -> None:
    job_dir = project.job_dir(program)
    header = program_header(project, program, require_database=False)
    bitstream = relative(project, program.bitstream)
    programming = BUILDSYS_DIR / "templates" / "program.sh"
    write_executable(job_dir / "program.sh", [
        *header,
        f"PROGRAM_ID={shlex.quote(program.identifier)}",
        f"BITSTREAM={shlex.quote(bitstream)}",
        *programming.read_text(encoding="utf-8").splitlines(),
    ])


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
