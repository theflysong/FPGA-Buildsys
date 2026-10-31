"""Program an FPGA through Vivado Hardware Manager."""

from __future__ import annotations

import argparse

from . import xpr_stage


__doc__ = "Program an existing XPR bitstream through Vivado Hardware Manager."


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target_id", metavar="project-id")
    parser.add_argument("--hw-server", default="localhost:3121", metavar="URL",
                        help="Vivado Hardware Server URL (default: localhost:3121)")
    parser.add_argument("--device", metavar="GLOB",
                        help="hardware device name glob; defaults to the first device")


def script_arguments(arguments: argparse.Namespace) -> tuple[str, ...]:
    result = ["--hw-server", arguments.hw_server]
    if arguments.device is not None:
        result.extend(("--device", arguments.device))
    return tuple(result)


def execute(project, target_id, task_args=(), script=None):
    return xpr_stage.execute(project, target_id, task_args, script)
