"""Persist and validate the toolchain selected for one project."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

from util import ConfigError


TOOLCHAINS = ("yosys", "vivado")
STAGES = ("synthesis", "implementation", "bitstream", "program")
STAGE_COMMANDS = {
    "yosys": {stage: f"yosys-{stage}" for stage in STAGES},
    "vivado": {stage: f"xpr-{stage}" for stage in STAGES},
}
YOSYS_COMMANDS = set(STAGE_COMMANDS["yosys"].values())
VIVADO_COMMANDS = {
    "xpr", "xpr-simulation", "xpr-synthesis", "xpr-implementation",
    "xpr-bitstream", "xpr-program",
}
SELECTION_HINT = "run buildsys toolchain yosys or buildsys toolchain vivado first"


def selection_path(root: Path) -> Path:
    return root / ".buildsys" / "toolchain.json"


def selected_toolchain(root: Path) -> str:
    path = selection_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"No toolchain selected for {root}; {SELECTION_HINT}") from exc
    except (ValueError, UnicodeError) as exc:
        raise ConfigError(f"{path}: invalid toolchain selection; {SELECTION_HINT}") from exc
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or name not in TOOLCHAINS:
        raise ConfigError(f"{path}: invalid toolchain selection; {SELECTION_HINT}")
    return name


def select_toolchain(root: Path, name: str) -> None:
    if name not in TOOLCHAINS:
        raise ConfigError(f"Unknown toolchain {name!r}; choose yosys or vivado")
    if not root.is_dir():
        raise ConfigError(f"{root}: project directory does not exist")
    path = selection_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="toolchain-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"name": name}, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def require_toolchain(root: Path, expected: str | None = None) -> str:
    name = selected_toolchain(root)
    if expected is not None and name != expected:
        raise ConfigError(
            f"Selected toolchain is {name!r}; this command requires {expected!r}; "
            f"run buildsys toolchain {expected} first"
        )
    return name


def command_toolchain(root: Path, command: str) -> str | None:
    if command in STAGES:
        return require_toolchain(root)
    if command in YOSYS_COMMANDS:
        return require_toolchain(root, "yosys")
    if command in VIVADO_COMMANDS:
        return require_toolchain(root, "vivado")
    if command in {"auxiliary", "script"}:
        return require_toolchain(root)
    return None


def resolve_command(root: Path, command: str) -> str:
    """Route shared FPGA stages to the project's selected backend."""
    if command in STAGES:
        return STAGE_COMMANDS[selected_toolchain(root)][command]
    return command


if __name__ == "__main__":
    # Generated FPGA jobs use the same validation when run without the CLI.
    try:
        if len(sys.argv) == 4 and sys.argv[2] == "--resolve":
            print(resolve_command(Path(sys.argv[1]), sys.argv[3]))
        else:
            require_toolchain(Path(sys.argv[1]), sys.argv[2])
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
