"""Print shell completion candidates without configuring a project."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from util import BUILDSYS_DIR


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("words", nargs=argparse.REMAINDER,
                        help="command arguments including the unfinished final word")


def run(arguments: argparse.Namespace) -> int:
    root = (arguments.project or Path.cwd()).expanduser().resolve()
    return subprocess.run(["bash", str(BUILDSYS_DIR / "completion.sh"), str(root), *arguments.words]).returncode
