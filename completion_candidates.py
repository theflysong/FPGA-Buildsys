"""Read-only, shell-independent completion candidate selection."""

from __future__ import annotations

import os
from pathlib import Path

from completion_ids import ID_RE, candidate_ids
from toolchains import STAGES, YOSYS_COMMANDS, resolve_command
from util import ConfigError


COMMANDS = (
    "model", "auxiliary", "script", "build", "simulate", "synthesis", "implementation",
    "bitstream", "program", "xpr", "xpr-simulation", "xpr-synthesis", "xpr-implementation",
    "yosys-synthesis", "yosys-implementation", "yosys-bitstream", "yosys-program",
    "xpr-bitstream", "xpr-program", "clean", "cleandist", "init", "init-venv", "install",
    "completion", "toolchain",
)
TERMINALS = ("bash", "powershell")


def directories(prefix: str) -> list[str]:
    """Complete directories relative to the caller, preserving the typed path."""
    split = max(prefix.rfind("/"), prefix.rfind("\\") if os.name == "nt" else -1) + 1
    parent, name = prefix[:split], prefix[split:]
    try:
        return [parent + entry.name + "/"
                for entry in sorted(Path(parent or ".").expanduser().iterdir())
                if entry.name.startswith(name) and entry.is_dir()]
    except OSError:
        return []


def target_ids(root: Path, *extensions: str) -> list[str]:
    result = []
    for extension in extensions:
        try:
            result.extend(path.stem for path in sorted((root / "build/auxiliary").glob("*" + extension))
                          if path.is_file() and ID_RE.fullmatch(path.stem))
        except OSError:
            pass
        kind = "simulation" if extension == ".f" else "project"
        result.extend(candidate_ids(root / "configuration.toml", kind))
    return result


def install_candidates(words: list[str]) -> list[str]:
    prefix = words[-1]
    if len(words) == 2:
        return ["buildsys", "completion", *directories(prefix)]
    if words[1] == "buildsys":
        return directories(prefix) if len(words) == 3 else []
    if words[1] != "completion":
        return []
    supplied = False
    directory_seen = False
    expecting_terminal = False
    for word in words[2:-1]:
        if expecting_terminal:
            expecting_terminal = False
        elif word == "--terminal":
            supplied = expecting_terminal = True
        elif word.startswith("--terminal="):
            supplied = True
        elif word.startswith("-") or directory_seen:
            return []
        else:
            directory_seen = True
    if expecting_terminal:
        return list(TERMINALS)
    if prefix.startswith("--terminal="):
        return [] if supplied else ["--terminal=" + terminal for terminal in TERMINALS]
    result = [] if supplied else ["--terminal"]
    if not directory_seen:
        result.extend(directories(prefix))
    return result


def program_candidates(root: Path, words: list[str], *, xpr: bool) -> list[str]:
    options = ("--hw-server", "--device") if xpr else ("--protocol", "--busdev-num", "--ftdi-serial")
    supplied: set[str] = set()
    expecting_value = False
    target_seen = False
    for word in words[1:-1]:
        if expecting_value:
            expecting_value = False
        elif word in options:
            supplied.add(word)
            expecting_value = True
        elif "=" in word and word.split("=", 1)[0] in options:
            supplied.add(word.split("=", 1)[0])
        elif word.startswith("-"):
            if not xpr:
                return []
        elif target_seen:
            return []
        else:
            target_seen = True
    if expecting_value:
        return []
    if not target_seen and (xpr or not words[-1].startswith("-")):
        return candidate_ids(root / "configuration.toml", "project") if xpr else target_ids(root, ".ys")
    if "--busdev-num" in supplied or "--ftdi-serial" in supplied:
        supplied.update(("--busdev-num", "--ftdi-serial"))
    return [option for option in options if option not in supplied]


def candidates(root: Path, words: list[str]) -> list[str]:
    """Return ordered, unique candidates for words ending in the current prefix."""
    words = words or [""]
    position = len(words) - 1
    command, prefix = words[0], words[-1]
    if position > 0 and command in STAGES:
        try:
            command = resolve_command(root, command)
        except (ConfigError, OSError):
            # Preserve useful completion before a toolchain has been selected.
            command = "yosys-" + command
    result: list[str] = []
    if position == 0:
        result = list(COMMANDS)
    elif command == "install":
        result = install_candidates(words)
    elif command in {"yosys-program", "xpr-program"}:
        result = program_candidates(root, words, xpr=command == "xpr-program")
    elif position == 1:
        if command == "toolchain":
            result = ["yosys", "vivado"]
        elif command in {"build", "simulate"}:
            result = target_ids(root, ".f")
        elif command in YOSYS_COMMANDS:
            result = target_ids(root, ".ys")
        elif command in {"clean", "cleandist"}:
            result = target_ids(root, ".f", ".ys")
        elif command == "xpr-simulation":
            result = candidate_ids(root / "configuration.toml", "simulation")
        elif command in {"xpr-synthesis", "xpr-implementation", "xpr-bitstream"}:
            result = candidate_ids(root / "configuration.toml", "project")
    return list(dict.fromkeys(item for item in result if item.startswith(prefix)))
