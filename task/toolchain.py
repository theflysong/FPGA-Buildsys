"""Select yosys or vivado for this project, or show the current selection."""

from __future__ import annotations

import argparse
from pathlib import Path

from toolchains import TOOLCHAINS, select_toolchain, selected_toolchain


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", nargs="?", choices=TOOLCHAINS, metavar="toolchain",
                        help="yosys or vivado; omit to show the current selection")


def run(arguments: argparse.Namespace) -> int:
    root = (arguments.project or Path.cwd()).expanduser().resolve()
    if arguments.name is not None:
        select_toolchain(root, arguments.name)
    print(selected_toolchain(root))
    return 0
