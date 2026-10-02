"""Create a template project in a directory containing only buildsys wrappers."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from util import BUILDSYS_DIR, ConfigError


def run(arguments: argparse.Namespace) -> int:
    root = (arguments.project or Path.cwd()).expanduser().resolve()
    if not root.is_dir():
        raise ConfigError(f"{root}: project directory does not exist")
    entries = {path.name: path for path in root.iterdir()}
    if set(entries) != {"buildsys", "buildsys.sh"} or not all(
        path.is_file() for path in entries.values()
    ):
        raise ConfigError(f"{root}: init requires a directory containing only buildsys and buildsys.sh files")

    template = BUILDSYS_DIR / "templates/template_project"
    for source in sorted(template.iterdir()):
        destination = root / source.name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    print(f"initialized template project in {root}")
    print("Run ./buildsys simulate example_simulation to generate the example waveform.")
    return 0
