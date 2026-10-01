#!/usr/bin/env python3
"""Build Verilog simulations and FPGA programs described by configuration.toml."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from planner import Planner
from task import COMMANDS
from util import ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="directory containing configuration.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, workflow in COMMANDS.items():
        command_parser = subparsers.add_parser(command, help=workflow.__doc__)
        if hasattr(workflow, "add_arguments"):
            workflow.add_arguments(command_parser)
    arguments = parser.parse_args(argv)
    workflow = COMMANDS[arguments.command]
    if arguments.command in Planner.TASKS and arguments.project is None:
        parser.error("--project is required for project commands")
    if hasattr(workflow, "validate_arguments"):
        workflow.validate_arguments(arguments, parser)
    try:
        if arguments.command in Planner.TASKS:
            task_args = workflow.script_arguments(arguments) if hasattr(workflow, "script_arguments") else ()
            Planner().run(arguments.project, arguments.command,
                          getattr(arguments, "target_id", None), task_args)
        else:
            return workflow.run(arguments)
    except (ConfigError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
