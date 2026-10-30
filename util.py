"""Shared validation, paths, shell generation, and process helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shlex
import subprocess
import tomllib

from models import CleanupTarget, Project, SynthesisProgram


BUILDSYS_DIR = Path(__file__).resolve().parent
ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
TIMESCALE_RE = re.compile(r"(?:1|10|100)(?:s|ms|us|ns|ps|fs)/(?:1|10|100)(?:s|ms|us|ns|ps|fs)\Z")
TEMPLATE_ARGUMENT_RE = re.compile(r"\$\$\(|\$\(([A-Za-z_][A-Za-z0-9_]*)\)")


class ConfigError(Exception):
    """An invalid project configuration, with its source location."""


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a TOML table")
    return data


def required_string(table: dict, key: str, location: str, pattern: re.Pattern | None = None) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{location}: {key} must be a nonempty string")
    if pattern is not None and not pattern.fullmatch(value):
        raise ConfigError(f"{location}: invalid {key}: {value!r}")
    return value


def task_identifier(table: dict, location: str) -> str:
    if "name" in table:
        raise ConfigError(f"{location}: name is obsolete for tasks; use id")
    return required_string(table, "id", location, ID_RE)


def string_list(table: dict, key: str, location: str) -> list[str]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{location}: {key} must be a list of nonempty strings")
    return value


def project_path(root: Path, value: str, location: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ConfigError(f"{location}: path must stay inside the project: {value!r}")
    return path


def external_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def output_directory(root: Path, directories: dict, key: str, location: str) -> Path:
    value = directories.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f'{location}: directories.{key} must be a nonempty path string; '
            f'use {key} = "build/{key}"'
        )
    return project_path(root, value, f"{location}: directories.{key}")


def output_name(value: str, location: str) -> str:
    if value in {".", ".."} or Path(value).name != value or any(c in value for c in '\n\r"\\'):
        raise ConfigError(f"{location}: expected a file name without directories: {value!r}")
    return value


def metadata_symbols(table: dict, key: str, path: Path) -> tuple[str, ...]:
    entries = table.get(key, [])
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: module.{key} must be an array of tables")
    result: list[str] = []
    for index, entry in enumerate(entries, 1):
        location = f"{path}: module.{key}[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{location}: expected a table")
        result.append(required_string(entry, "name", location, SYMBOL_RE))
    if len(result) != len(set(result)):
        raise ConfigError(f"{path}: duplicate module.{key} symbol")
    return tuple(result)


def source_closure(project: Project, top: str) -> list[str]:
    return source_order(project, project.exports[top])


def source_order(project: Project, source: str) -> list[str]:
    return [*project.sources[source].closure, source]


def relative(project: Project, path: Path) -> str:
    return path.relative_to(project.root).as_posix()


def yosys_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_template(template_name: str, /, **arguments: str) -> str:
    """Substitute $(name) once; $$( emits a literal $( for shell commands."""
    path = BUILDSYS_DIR / "templates" / template_name

    def substitute(match: re.Match[str]) -> str:
        if match.group(0) == "$$(":
            return "$("
        key = match.group(1)
        if key not in arguments:
            raise ConfigError(f"{path}: missing template argument {key!r}")
        return arguments[key]

    return TEMPLATE_ARGUMENT_RE.sub(substitute, path.read_text(encoding="utf-8"))


def write_template(path: Path, template_name: str, *, newline: str = "\n",
                   executable: bool = False, **arguments: str) -> None:
    content = render_template(template_name, **arguments)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline=newline)
    if executable:
        path.chmod(0o755)


def write_executable(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


def task_header(project: Project, *, temporary: bool = False) -> list[str]:
    root = (shlex.quote(str(project.root)) if temporary else
            render_template("shell/task-root.sh").rstrip("\n"))
    return render_template("shell/task-header.sh", project_root=root).splitlines()


def fpga_config_path(root: Path, identifier: str) -> Path:
    return root / "build" / "fpga" / f"{identifier}.toml"


def toolchain_header(toolchain_roots: tuple[Path, ...]) -> list[str]:
    if not toolchain_roots:
        return []
    roots = " ".join(shlex.quote(str(root)) for root in toolchain_roots)
    return render_template("shell/toolchain-header.sh", roots=roots).splitlines()


def selected_toolchain_header(name: str) -> list[str]:
    validator = shlex.quote(str(BUILDSYS_DIR / "toolchains.py"))
    return render_template("shell/selected-toolchain.sh", validator=validator,
                           toolchain=shlex.quote(name)).splitlines()


def program_header(project: Project, program: SynthesisProgram) -> list[str]:
    python_paths = " ".join(shlex.quote(str(path)) for path in program.fpga.python_paths)
    return render_template(
        "yosys/program-header.sh",
        task_header="\n".join(task_header(project)),
        selection="\n".join(selected_toolchain_header("yosys")),
        part=shlex.quote(program.fpga.part),
        database=shlex.quote(str(program.fpga.xray_database) if program.fpga.xray_database else ""),
        python_paths=python_paths,
        config=shlex.quote(relative(project, fpga_config_path(project.root, program.fpga.identifier))),
        toolchain_header="\n".join(toolchain_header(program.fpga.toolchain_roots)),
        pythonpath_header=render_template("shell/pythonpath-header.sh").rstrip("\n")
        if program.fpga.python_paths else "",
    ).splitlines()


def selected_targets(project: Project, target_id: str | None) -> tuple[CleanupTarget, ...]:
    targets = project.cleanup_targets
    if target_id is None:
        return targets
    for target in targets:
        if target.identifier == target_id:
            return (target,)
    raise ConfigError(f"{project.root / 'configuration.toml'}: unknown target id {target_id!r}")


def require_simulation(project: Project, target_id: str | None) -> None:
    if target_id not in {item.identifier for item in project.simulations}:
        raise ConfigError(f"{project.root / 'configuration.toml'}: unknown simulation {target_id!r}")


def require_program(project: Project, target_id: str | None) -> None:
    if target_id not in {item.identifier for item in project.programs}:
        raise ConfigError(f"{project.root / 'configuration.toml'}: unknown project {target_id!r}")


def require_fpga_build(project: Project, target_id: str | None) -> None:
    require_program(project, target_id)
    target = next(item for item in project.programs if item.identifier == target_id)
    assert isinstance(target, SynthesisProgram)
    if target.fpga.xray_database is None:
        path = fpga_config_path(project.root, target.fpga.identifier)
        raise ConfigError(f"{path}: fill xray-database before building project {target_id!r}; toolchain-root is optional")

    if not target.fpga.python_paths:
        path = fpga_config_path(project.root, target.fpga.identifier)
        raise ConfigError(f"{path}: fill PYTHONPATH with Python module directories before building project {target_id!r}")


def add_target_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target_id")


def add_optional_target_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target_id", nargs="?")


def execute_job(project: Project, command: str, target_id: str | None,
                task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    if script is not None:
        args = ["bash", str(script)]
    else:
        args = [str(project.script), command]
        if target_id is not None:
            args.append(target_id)
        args.extend(task_args)
    subprocess.run(args, cwd=project.root, check=True)
