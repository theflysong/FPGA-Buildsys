#!/usr/bin/env python3
"""Build Verilog simulations and FPGA programs described by configuration.toml."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from planner import Planner
from task import COMMANDS
from toolchains import STAGES, resolve_command
from util import ConfigError


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Resolve before parsing stage options: each backend has its own program flags.
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--project", type=Path)
    probe.add_argument("command", nargs="?")
    preliminary, _ = probe.parse_known_args(argv)
    workflows = dict(COMMANDS)
    if preliminary.command in STAGES and preliminary.project is not None:
        try:
            command = resolve_command(preliminary.project.expanduser().resolve(), preliminary.command)
            workflows[preliminary.command] = COMMANDS[command]
        except (ConfigError, OSError) as exc:
            if not any(option in argv for option in ("-h", "--help")):
                print(f"error: {exc}", file=sys.stderr)
                return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, help="directory containing configuration.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, workflow in workflows.items():
        help_text = (f"Run {command} using the selected toolchain."
                     if command in STAGES else workflow.__doc__)
        command_parser = subparsers.add_parser(command, help=help_text)
        if hasattr(workflow, "add_arguments"):
            workflow.add_arguments(command_parser)
    arguments = parser.parse_args(argv)
    workflow = workflows[arguments.command]
    project_command = arguments.command in Planner.TASKS or arguments.command in STAGES
    if project_command and arguments.project is None:
        parser.error("--project is required for project commands")
    if hasattr(workflow, "validate_arguments"):
        workflow.validate_arguments(arguments, parser)
    try:
        if project_command:
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
