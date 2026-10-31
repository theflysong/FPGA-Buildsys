"""Run a configured XPR simulation through Vivado batch mode."""

from __future__ import annotations

import argparse

from . import xpr_stage


__doc__ = "Run one simulation from an existing Vivado XPR project."


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target_id", metavar="simulation-id")
    parser.add_argument("legacy_simulation_id", nargs="?", help=argparse.SUPPRESS)


def validate_arguments(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if arguments.legacy_simulation_id is not None:
        parser.error("xpr-simulation now takes only a simulation-id; omit the old xpr-id")


def execute(project, target_id, task_args=(), script=None):
    return xpr_stage.execute(project, target_id, task_args, script)
