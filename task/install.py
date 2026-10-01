"""Install buildsys wrappers or Bash completion."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess

from util import BUILDSYS_DIR, ConfigError, write_executable


def install_wrappers(directory: Path) -> None:
    target = directory.expanduser().resolve()
    if not target.is_dir():
        raise ConfigError(f"{target}: install directory does not exist")
    main_relative = os.path.relpath(BUILDSYS_DIR / "main.py", target)
    write_executable(target / "buildsys.sh", [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
        f"MAIN_REL={shlex.quote(main_relative)}",
        'exec python3 "$PROJECT_DIR/$MAIN_REL" --project "$PROJECT_DIR" "$@"',
    ])
    write_executable(target / "buildsys", [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
        'exec "$SCRIPT_DIR/buildsys.sh" "$@"',
    ])
    print(f"installed {target / 'buildsys'} and {target / 'buildsys.sh'}")


def install_completion(directory: Path) -> None:
    script = BUILDSYS_DIR / "install-completion.sh"
    target = directory.expanduser().resolve()
    subprocess.run(["bash", str(script), str(target)], check=True)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("item", nargs="?", default="buildsys",
                        help="buildsys (default) or completion; a lone directory installs buildsys")
    parser.add_argument("directory", nargs="?", type=Path,
                        help="existing destination directory; defaults to cwd for buildsys or the system completion directory")


def validate_arguments(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if arguments.item not in {"buildsys", "completion"} and arguments.directory is not None:
        parser.error(f"unknown install item {arguments.item!r}; choose buildsys or completion")


def run(arguments: argparse.Namespace) -> int:
    if arguments.item == "completion":
        install_completion(arguments.directory or Path("/usr/share/bash-completion/completions"))
    elif arguments.item == "buildsys":
        install_wrappers(arguments.directory or Path.cwd())
    else:
        # Preserve the original `install <directory>` shorthand.
        install_wrappers(Path(arguments.item))
    return 0
