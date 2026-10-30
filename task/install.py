"""Install buildsys wrappers or shell completion."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil

from completion_candidates import TERMINALS
from powershell_completion import install as install_powershell_completion
from util import BUILDSYS_DIR, ConfigError, write_template


def install_wrappers(directory: Path) -> None:
    target = directory.expanduser().resolve()
    if not target.is_dir():
        raise ConfigError(f"{target}: install directory does not exist")
    main_relative = os.path.relpath(BUILDSYS_DIR / "main.py", target)
    shell_relative = main_relative.replace(os.sep, "/")
    write_template(target / "buildsys.sh", "buildsys.sh.in", executable=True,
                   main_relative=shlex.quote(shell_relative))
    write_template(target / "buildsys", "buildsys.in", executable=True)
    # Batch expands literal percent signs even inside double quotes. Disable
    # delayed expansion so exclamation marks in project paths survive as well.
    batch_relative = main_relative.replace("/", "\\").replace("%", "%%")
    write_template(target / "buildsys.bat", "buildsys.bat.in", newline="\r\n",
                   main_relative=batch_relative)
    print(f"installed {target / 'buildsys'}, {target / 'buildsys.sh'} and {target / 'buildsys.bat'}")


def default_terminal() -> str:
    return "powershell" if os.name == "nt" else "bash"


def install_completion(directory: Path | None, terminal: str) -> None:
    if terminal == "powershell":
        install_powershell_completion(directory)
        return
    target = (directory or Path("/usr/share/bash-completion/completions")).expanduser().resolve()
    if not target.is_dir():
        raise ConfigError(f"{target}: install directory does not exist")
    for name in ("buildsys", "buildsys.sh"):
        destination = target / name
        shutil.copyfile(BUILDSYS_DIR / "bash-completion/buildsys.bash", destination)
        destination.chmod(0o644)
        print(f"installed {destination}")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("item", nargs="?", default="buildsys",
                        help="buildsys (default) or completion; a lone directory installs buildsys")
    parser.add_argument("directory", nargs="?", type=Path,
                        help="existing destination directory; defaults to cwd for buildsys or the terminal's completion directory")
    parser.add_argument("--terminal", choices=TERMINALS,
                        help="completion terminal (default: powershell on Windows, bash elsewhere)")


def validate_arguments(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if arguments.terminal is not None and arguments.item != "completion":
        parser.error("--terminal is only valid for install completion")
    if arguments.item not in {"buildsys", "completion"} and arguments.directory is not None:
        parser.error(f"unknown install item {arguments.item!r}; choose buildsys or completion")


def run(arguments: argparse.Namespace) -> int:
    if arguments.item == "completion":
        install_completion(arguments.directory, arguments.terminal or default_terminal())
    elif arguments.item == "buildsys":
        install_wrappers(arguments.directory or Path.cwd())
    else:
        # Preserve the original `install <directory>` shorthand.
        install_wrappers(Path(arguments.item))
    return 0
