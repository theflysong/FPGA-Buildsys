"""Run a configured XPR simulation through Vivado batch mode."""

from __future__ import annotations

import argparse

from . import xpr_stage


__doc__ = "Run one simulation from an existing Vivado XPR project."


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target_id", metavar="xpr-id")
    parser.add_argument("simulation_id", metavar="simulation-id", nargs="?")


def script_arguments(arguments: argparse.Namespace) -> tuple[str, ...]:
    return (arguments.simulation_id,) if arguments.simulation_id is not None else ()


def execute(project, target_id, task_args=(), script=None):
    return xpr_stage.execute(project, target_id, task_args, script)
