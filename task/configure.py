"""Read project configuration and initialize validated FPGA settings."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from models import (
    CleanupTarget, Fpga, ImplementationProgram, Program, ProgrammingTarget,
    Project, Simulation, SynthesisProgram,
)
from toolchains import command_toolchain, resolve_command
from util import (
    ConfigError, ID_RE, SYMBOL_RE, TIMESCALE_RE, fpga_config_path,
    output_directory, output_name, project_path, read_toml, required_string,
    string_list, task_identifier,
)
from .vivado.configure import configure_xpr, configure_xpr_stage
from .yosys.configure import toolchain_roots


def task_index(data: dict, config_path: Path) -> dict[str, tuple[str, dict, str]]:
    if "program" in data:
        raise ConfigError(f"{config_path}: [[program]] is obsolete; rename it to [[project]]")
    entries: dict[str, tuple[str, dict, str]] = {}
    for kind in ("simulation", "project"):
        raw_entries = data.get(kind, [])
        if not isinstance(raw_entries, list):
            raise ConfigError(f"{config_path}: [[simulation]] and [[project]] must be arrays of tables")
        for index, raw in enumerate(raw_entries, 1):
            location = f"{config_path}: {kind}[{index}]"
            if not isinstance(raw, dict):
                raise ConfigError(f"{location}: expected a table")
            task_id = task_identifier(raw, location)
            if task_id in entries:
                raise ConfigError(
                    f"{location}: duplicate task id {task_id!r}; already used by {entries[task_id][2]}"
                )
            entries[task_id] = (kind, raw, location)
    if not entries:
        raise ConfigError(f"{config_path}: at least one [[simulation]] or [[project]] is required")
    return entries


def source_directories(root: Path, directories: dict, config_path: Path,
                       key: str = "sources") -> tuple[Path, ...]:
    if key == "simulation" and key not in directories:
        return ()
    source_dirs = string_list(directories, key, str(config_path))
    if key == "sources" and not source_dirs:
        raise ConfigError(f"{config_path}: directories.sources must not be empty")
    result = [project_path(root, value, f"{config_path}: directories.{key}") for value in source_dirs]
    return tuple(dict.fromkeys(result))


def fpga_index(data: dict, config_path: Path) -> dict[str, tuple[dict, str]]:
    raw_fpgas = data.get("fpga", [])
    if not isinstance(raw_fpgas, list):
        raise ConfigError(f"{config_path}: [[fpga]] must be an array of tables")
    result: dict[str, tuple[dict, str]] = {}
    for index, raw in enumerate(raw_fpgas, 1):
        location = f"{config_path}: fpga[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{location}: expected a table")
        identifier = required_string(raw, "id", location, ID_RE)
        if identifier in result:
            raise ConfigError(f"{location}: duplicate fpga id {identifier!r}")
        result[identifier] = (raw, location)
    return result


def parse_fpga(root: Path, fpga_id: str, raw: dict, location: str) -> Fpga:
    part = required_string(raw, "part", location)
    legacy = [key for key in ("xray-database", "toolchain-root", "PYTHONPATH") if key in raw]
    if legacy:
        path = fpga_config_path(root, fpga_id)
        raise ConfigError(f"{location}: move {', '.join(legacy)} to {path} and remove these fields from configuration.toml")
    return Fpga(fpga_id, part, None, (), ())


def constraint_path(root: Path, directories: dict, config_path: Path,
                    raw: dict, location: str) -> Path:
    constraint_dirs = string_list(directories, "constraints", str(config_path))
    if len(constraint_dirs) != 1:
        raise ConfigError(f"{config_path}: directories.constraints must contain one path")
    directory = project_path(root, constraint_dirs[0], f"{config_path}: directories.constraints")
    path = directory / output_name(required_string(raw, "constraints", location), location)
    if not path.is_file():
        raise ConfigError(f"{location}: constraints file does not exist: {path}")
    return path


def configure(root: Path, command: str = "script", target_id: str | None = None) -> Project:
    root = root.expanduser().resolve()
    command = resolve_command(root, command)
    toolchain = command_toolchain(root, command)
    return replace(_configure(root, command, target_id, toolchain), toolchain=toolchain)


def _configure(root: Path, command: str, target_id: str | None, toolchain: str | None) -> Project:
    stage = command.removeprefix("yosys-")
    config_path = root / "configuration.toml"
    data = read_toml(config_path)
    identifier = required_string(data, "id", str(config_path), ID_RE)
    required_string(data, "name", str(config_path))
    entries = task_index(data, config_path)
    if command == "model":
        directories = data.get("directories")
        if not isinstance(directories, dict):
            raise ConfigError(f"{config_path}: [directories] is required")
        return Project(root, identifier, (), (), command=command,
                       source_directories=source_directories(root, directories, config_path),
                       simulation_directories=source_directories(root, directories, config_path, "simulation"))
    if command == "xpr":
        return configure_xpr(root, data, config_path, identifier, entries, target_id)
    if command.startswith("xpr-"):
        return configure_xpr_stage(root, data, config_path, identifier, entries, target_id, command)
    full = command in {"auxiliary", "script"}
    cleaning = command in {"clean", "cleandist"}
    all_targets = full or (cleaning and target_id is None)
    if not all_targets:
        expected = ("target id" if cleaning else
                    "simulation" if command in {"build", "simulate"} else "project")
        if target_id not in entries or (not cleaning and entries[target_id][0] != expected):
            raise ConfigError(f"{config_path}: unknown {expected} {target_id!r}")
    selected = entries if all_targets else {target_id: entries[target_id]}
    directories = data.get("directories")
    if not isinstance(directories, dict):
        raise ConfigError(f"{config_path}: [directories] is required")

    seen_outputs: set[Path] = set()

    def output(raw: dict, kind: str, location: str) -> Path:
        directory = output_directory(root, directories, kind, str(config_path))
        path = directory / output_name(required_string(raw, kind, location), location)
        register_output(path, location)
        return path

    def register_output(path: Path, location: str) -> None:
        if path in seen_outputs:
            raise ConfigError(f"{location}: duplicate output {path}")
        seen_outputs.add(path)

    needs_fpga = (full and toolchain == "yosys") or (
        not full and not cleaning and any(kind == "project" for kind, _, _ in selected.values())
    )
    raw_fpgas = fpga_index(data, config_path) if needs_fpga else {}
    fpgas: dict[str, Fpga] = {}

    def public_fpga(fpga_id: str, location: str) -> Fpga:
        if fpga_id not in raw_fpgas:
            raise ConfigError(f"{location}: unknown fpga id {fpga_id!r}")
        if fpga_id not in fpgas:
            raw, fpga_location = raw_fpgas[fpga_id]
            fpgas[fpga_id] = parse_fpga(root, fpga_id, raw, fpga_location)
        return fpgas[fpga_id]

    if full:
        for fpga_id in raw_fpgas:
            public_fpga(fpga_id, str(config_path))

    simulations: list[Simulation] = []
    programs: list[SynthesisProgram | ProgrammingTarget] = []
    cleanup_targets: list[CleanupTarget] = []
    for task_id, (kind, raw, location) in selected.items():
        if full and toolchain == "vivado" and kind == "project":
            continue
        if cleaning:
            kinds = ("vvp", "vcd") if kind == "simulation" else ("synthesis", "implementation", "bitstream")
            outputs = tuple(output(raw, name, location) for name in kinds)
            if kind == "project":
                frames = outputs[-1].with_suffix(".frames")
                register_output(frames, location)
                outputs = (*outputs, frames)
            suffix = ".f" if kind == "simulation" else ".ys"
            cleanup_targets.append(CleanupTarget(task_id, outputs, root / "build/auxiliary" / f"{task_id}{suffix}"))
            continue
        if kind == "simulation":
            top = required_string(raw, "top-symbol", location, SYMBOL_RE)
            timescale = required_string(raw, "timescale", location, TIMESCALE_RE)
            vvp, vcd = (output(raw, name, location) for name in ("vvp", "vcd"))
            simulations.append(Simulation(task_id, top, timescale, vvp, vcd))
            if full:
                cleanup_targets.append(CleanupTarget(task_id, (vvp, vcd), root / "build/auxiliary" / f"{task_id}.f"))
            continue

        fpga_id = required_string(raw, "fpga", location, ID_RE)
        if stage == "program":
            if fpga_id not in raw_fpgas:
                raise ConfigError(f"{location}: unknown fpga id {fpga_id!r}")
            bitstream = output(raw, "bitstream", location)
            local = fpga_config_path(root, fpga_id)
            roots = toolchain_roots(root, read_toml(local), local) if local.exists() or local.is_symlink() else ()
            programs.append(ProgrammingTarget(task_id, bitstream, roots))
            continue

        fpga = public_fpga(fpga_id, location)
        top = required_string(raw, "top-symbol", location, SYMBOL_RE)
        synthesis = output(raw, "synthesis", location)
        if stage == "synthesis":
            programs.append(SynthesisProgram(task_id, fpga, top, synthesis))
            continue
        implementation = output(raw, "implementation", location)
        constraints = constraint_path(root, directories, config_path, raw, location)
        if constraints in seen_outputs:
            raise ConfigError(f"{location}: duplicate output {constraints}")
        if stage == "implementation":
            programs.append(ImplementationProgram(task_id, fpga, top, synthesis, implementation, constraints))
            continue
        bitstream = output(raw, "bitstream", location)
        frames = bitstream.with_suffix(".frames")
        register_output(frames, location)
        if constraints in (bitstream, frames):
            raise ConfigError(f"{location}: duplicate output {constraints}")
        programs.append(Program(task_id, fpga, top, synthesis, implementation, constraints, bitstream))
        cleanup_targets.append(CleanupTarget(task_id, (synthesis, implementation, frames, bitstream),
                                             root / "build/auxiliary" / f"{task_id}.ys"))

    needs_sources = not cleaning and stage != "program"
    return Project(
        root, identifier, tuple(simulations), tuple(programs),
        command=command,
        simulation_ids=tuple(key for key, entry in entries.items() if entry[0] == "simulation"),
        program_ids=tuple(key for key, entry in entries.items()
                          if entry[0] == "project" and toolchain != "vivado"),
        cleanup_targets=tuple(cleanup_targets),
        source_directories=source_directories(root, directories, config_path) if needs_sources else (),
        simulation_directories=source_directories(root, directories, config_path, "simulation") if needs_sources else (),
        fpgas=tuple(fpgas.values()),
    )
