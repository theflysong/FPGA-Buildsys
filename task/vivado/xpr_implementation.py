"""Run Vivado implementation for an existing XPR project."""

from __future__ import annotations

import argparse

from . import xpr_stage


__doc__ = "Run implementation in an existing Vivado XPR project."


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target_id", metavar="xpr-id")


def execute(project, target_id, task_args=(), script=None):
    return xpr_stage.execute(project, target_id, task_args, script)
