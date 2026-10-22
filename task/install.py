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
        'MAIN_PATH="$PROJECT_DIR/$MAIN_REL"',
        'BUILDSYS_DIR="$(cd -- "$(dirname -- "$MAIN_PATH")" && pwd)"',
        'VENV_DIR="$BUILDSYS_DIR/.venv"',
        'if [[ -d "$VENV_DIR" ]]; then',
        '    if [[ ! -f "$VENV_DIR/bin/activate" || ! -x "$VENV_DIR/bin/python" ]]; then',
        '        printf "error: incomplete buildsys virtual environment: %s\\n" "$VENV_DIR" >&2',
        '        exit 1',
        '    fi',
        '    if ! source "$VENV_DIR/bin/activate"; then',
        '        printf "error: failed to activate buildsys virtual environment: %s\\n" "$VENV_DIR" >&2',
        '        exit 1',
        '    fi',
        '    exec "$VENV_DIR/bin/python" "$MAIN_PATH" --project "$PROJECT_DIR" "$@"',
        'fi',
        'exec python3 "$MAIN_PATH" --project "$PROJECT_DIR" "$@"',
    ])
    write_executable(target / "buildsys", [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
        'exec "$SCRIPT_DIR/buildsys.sh" "$@"',
    ])
    # Batch expands literal percent signs even inside double quotes. Disable
    # delayed expansion so exclamation marks in project paths survive as well.
    batch_relative = main_relative.replace("/", "\\").replace("%", "%%")
    (target / "buildsys.bat").write_bytes((
        "@echo off\r\n"
        "setlocal DisableDelayedExpansion\r\n"
        # Use the wrapper's short path for internal batch-to-batch calls. This
        # prevents a literal percent sign in an installation path from being
        # treated as an environment-variable expansion by CALL.
        f'for %%I in ("%~sdp0{batch_relative}") do set "BUILDSYS_DIR=%%~dpI"\r\n'
        'set "BUILDSYS_VENV=%BUILDSYS_DIR%.venv"\r\n'
        'if not exist "%BUILDSYS_VENV%\\" goto system_python\r\n'
        'if not exist "%BUILDSYS_VENV%\\Scripts\\activate.bat" goto incomplete_venv\r\n'
        'if not exist "%BUILDSYS_VENV%\\Scripts\\python.exe" goto incomplete_venv\r\n'
        'call "%BUILDSYS_VENV%\\Scripts\\activate.bat"\r\n'
        'if errorlevel 1 goto activation_failed\r\n'
        f'"%BUILDSYS_VENV%\\Scripts\\python.exe" "%~dp0{batch_relative}" --project "%~dp0." %*\r\n'
        "exit /b %errorlevel%\r\n"
        ":incomplete_venv\r\n"
        'echo error: incomplete buildsys virtual environment: "%BUILDSYS_VENV%" >&2\r\n'
        "exit /b 1\r\n"
        ":activation_failed\r\n"
        'echo error: failed to activate buildsys virtual environment: "%BUILDSYS_VENV%" >&2\r\n'
        "exit /b 1\r\n"
        ":system_python\r\n"
        f'python "%~dp0{batch_relative}" --project "%~dp0." %*\r\n'
        "exit /b %errorlevel%\r\n"
    ).encode("utf-8"))
    print(f"installed {target / 'buildsys'}, {target / 'buildsys.sh'} and {target / 'buildsys.bat'}")


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
