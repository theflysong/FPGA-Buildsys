"""Create the shared buildsys virtual environment and install its dependencies."""

from __future__ import annotations

import argparse
import os
import subprocess
import venv

from util import BUILDSYS_DIR, ConfigError


def run(arguments: argparse.Namespace) -> int:
    root = BUILDSYS_DIR / ".venv"
    scripts = root / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    activate = scripts / ("activate.bat" if os.name == "nt" else "activate")
    if root.exists() and not root.is_dir():
        raise ConfigError(f"{root}: virtual environment path is not a directory")
    if not (python.is_file() and activate.is_file()):
        venv.EnvBuilder(with_pip=True).create(root)
    if not python.is_file():
        raise ConfigError(f"{root}: virtual environment creation did not produce a Python executable")
    if not (BUILDSYS_DIR / "requirements.txt").is_file():
        raise ConfigError(f"{BUILDSYS_DIR}: requirements.txt does not exist")
    subprocess.run([
        str(python), "-m", "pip", "install", "-r", str(BUILDSYS_DIR / "requirements.txt"),
    ], check=True)
    print(f"initialized buildsys virtual environment in {root}")
    return 0
