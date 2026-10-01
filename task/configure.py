"""Read and validate project configuration and source metadata."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys

from models import Fpga, Program, Project, Simulation
from util import (
    ConfigError, ID_RE, SYMBOL_RE, TIMESCALE_RE, external_path, fpga_config_path, metadata_symbols,
    output_directory, output_name, project_path, read_toml, required_string,
    string_list, task_identifier,
)


FPGA_TEMPLATE = '''# 本地 FPGA 配置；相对路径以项目根目录为基准，也支持绝对路径。
# 必填：Project X-Ray 数据库目录。
xray-database = ""

# 可选：按列表顺序查找各目录及其 bin/；空列表使用 PATH。
toolchain-root = []
'''


def initialize_fpga_config(root: Path, fpga: Fpga) -> bool:
    path = fpga_config_path(root, fpga.identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(FPGA_TEMPLATE)
    return True


def load_fpga_config(root: Path, fpga: Fpga) -> Fpga:
    path = fpga_config_path(root, fpga.identifier)
    data = read_toml(path)
    database = data.get("xray-database", "")
    if not isinstance(database, str):
        raise ConfigError(f"{path}: xray-database must be a string; leave it empty if not configured")
    roots = data.get("toolchain-root", [])
    if not isinstance(roots, list) or not all(isinstance(value, str) and value.strip() for value in roots):
        raise ConfigError(
            f'{path}: toolchain-root must be a list of nonempty strings; '
            'use ["path"] for one directory or [] to use PATH'
        )
    return replace(
        fpga,
        xray_database=external_path(root, database) if database.strip() else None,
        toolchain_roots=tuple(external_path(root, value) for value in roots),
    )


def configure(root: Path) -> Project:
    root = root.resolve()
    config_path = root / "configuration.toml"
    data = read_toml(config_path)
    identifier = required_string(data, "id", str(config_path), ID_RE)
    required_string(data, "name", str(config_path))

    raw_simulations = data.get("simulation", [])
    raw_programs = data.get("program", [])
    if not isinstance(raw_simulations, list) or not isinstance(raw_programs, list):
        raise ConfigError(f"{config_path}: [[simulation]] and [[program]] must be arrays of tables")
    if not raw_simulations and not raw_programs:
        raise ConfigError(f"{config_path}: at least one [[simulation]] or [[program]] is required")

    directories = data.get("directories")
    if not isinstance(directories, dict):
        raise ConfigError(f"{config_path}: [directories] is required")
    source_dirs = string_list(directories, "sources", str(config_path))
    if not source_dirs:
        raise ConfigError(f"{config_path}: directories.sources must not be empty")
    output_dirs: dict[str, Path] = {}
    if raw_simulations:
        for kind in ("vvp", "vcd"):
            output_dirs[kind] = output_directory(root, directories, kind, str(config_path))
    if raw_programs:
        constraint_dirs = string_list(directories, "constraints", str(config_path))
        if len(constraint_dirs) != 1:
            raise ConfigError(f"{config_path}: directories.constraints must contain one path")
        output_dirs["constraints"] = project_path(
            root, constraint_dirs[0], f"{config_path}: directories.constraints"
        )
        for kind in ("synthesis", "implementation", "bitstream"):
            output_dirs[kind] = output_directory(root, directories, kind, str(config_path))

    simulations: list[Simulation] = []
    seen_task_ids: dict[str, str] = {}
    seen_outputs: set[Path] = set()
    for index, raw in enumerate(raw_simulations, 1):
        location = f"{config_path}: simulation[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{location}: expected a table")
        task_id = task_identifier(raw, location)
        if task_id in seen_task_ids:
            raise ConfigError(f"{location}: duplicate task id {task_id!r}; already used by {seen_task_ids[task_id]}")
        seen_task_ids[task_id] = location
        top = required_string(raw, "top-symbol", location, SYMBOL_RE)
        timescale = required_string(raw, "timescale", location, TIMESCALE_RE)
        vvp = output_dirs["vvp"] / output_name(required_string(raw, "vvp", location), location)
        vcd = output_dirs["vcd"] / output_name(required_string(raw, "vcd", location), location)
        for output in (vvp, vcd):
            if output in seen_outputs:
                raise ConfigError(f"{location}: duplicate output {output}")
            seen_outputs.add(output)
        simulations.append(Simulation(task_id, top, timescale, vvp, vcd))

    raw_fpgas = data.get("fpga", [])
    if not isinstance(raw_fpgas, list):
        raise ConfigError(f"{config_path}: [[fpga]] must be an array of tables")
    fpgas: dict[str, Fpga] = {}
    for index, raw in enumerate(raw_fpgas, 1):
        location = f"{config_path}: fpga[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{location}: expected a table")
        fpga_id = required_string(raw, "id", location, ID_RE)
        if fpga_id in fpgas:
            raise ConfigError(f"{location}: duplicate fpga id {fpga_id!r}")
        part = required_string(raw, "part", location)
        legacy = [key for key in ("xray-database", "toolchain-root") if key in raw]
        if legacy:
            path = fpga_config_path(root, fpga_id)
            raise ConfigError(f"{location}: move {', '.join(legacy)} to {path} and remove these fields from configuration.toml")
        fpgas[fpga_id] = Fpga(fpga_id, part, None, ())

    programs: list[Program] = []
    for index, raw in enumerate(raw_programs, 1):
        location = f"{config_path}: program[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{location}: expected a table")
        task_id = task_identifier(raw, location)
        if task_id in seen_task_ids:
            raise ConfigError(f"{location}: duplicate task id {task_id!r}; already used by {seen_task_ids[task_id]}")
        seen_task_ids[task_id] = location
        fpga_id = required_string(raw, "fpga", location, ID_RE)
        if fpga_id not in fpgas:
            raise ConfigError(f"{location}: unknown fpga id {fpga_id!r}")
        top = required_string(raw, "top-symbol", location, SYMBOL_RE)
        paths = {
            kind: output_dirs[kind] / output_name(required_string(raw, kind, location), location)
            for kind in ("synthesis", "implementation", "bitstream", "constraints")
        }
        if not paths["constraints"].is_file():
            raise ConfigError(f"{location}: constraints file does not exist: {paths['constraints']}")
        program = Program(task_id, fpgas[fpga_id], top, paths["synthesis"],
                          paths["implementation"], paths["bitstream"], paths["constraints"])
        for output in (program.synthesis, program.implementation, program.bitstream,
                       program.frames):
            if output in seen_outputs or output == program.constraints:
                raise ConfigError(f"{location}: duplicate output {output}")
            seen_outputs.add(output)
        programs.append(program)

    sources: set[Path] = set()
    for value in source_dirs:
        directory = project_path(root, value, f"{config_path}: directories.sources")
        if not directory.is_dir():
            raise ConfigError(f"{config_path}: source directory does not exist: {directory}")
        sources.update(path for path in directory.rglob("*") if path.is_file() and path.suffix in {".v", ".sv"})
    if not sources:
        raise ConfigError(f"{config_path}: no Verilog source files in directories.sources")

    exports: dict[str, str] = {}
    imports: dict[str, tuple[str, ...]] = {}
    for source in sorted(sources):
        metadata_path = source.with_suffix(".toml")
        metadata = read_toml(metadata_path)
        module = metadata.get("module")
        if not isinstance(module, dict):
            raise ConfigError(f"{metadata_path}: [module] metadata is required")
        relative = source.relative_to(root).as_posix()
        imported = metadata_symbols(module, "import", metadata_path)
        exported = metadata_symbols(module, "export", metadata_path)
        imports[relative] = imported
        for symbol in exported:
            if symbol in exports:
                raise ConfigError(
                    f"{metadata_path}: duplicate export {symbol!r}; already exported by {exports[symbol]}"
                )
            exports[symbol] = relative

    for source, symbols in imports.items():
        for symbol in symbols:
            if symbol not in exports:
                raise ConfigError(f"{root / Path(source).with_suffix('.toml')}: unresolved import {symbol!r}")
    for simulation in simulations:
        if simulation.top not in exports:
            raise ConfigError(f"{config_path}: simulation {simulation.identifier!r} has no exported top-symbol {simulation.top!r}")
    for program in programs:
        if program.top not in exports:
            raise ConfigError(f"{config_path}: program {program.identifier!r} has no exported top-symbol {program.top!r}")

    # User-owned local files are initialized only after public configuration is valid.
    created = [fpga_config_path(root, fpga.identifier)
               for fpga in fpgas.values() if initialize_fpga_config(root, fpga)]
    fpgas = {identifier: load_fpga_config(root, fpga) for identifier, fpga in fpgas.items()}
    programs = [replace(program, fpga=fpgas[program.fpga.identifier]) for program in programs]
    for path in created:
        print(f"Created {path}; fill xray-database before FPGA builds. "
              "toolchain-root is optional; use [] to use PATH.", file=sys.stderr)
    return Project(root, identifier, tuple(simulations), tuple(programs), exports, imports)
