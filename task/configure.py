"""Read and validate project configuration and source metadata."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys

from models import (
    CleanupTarget, Fpga, ImplementationProgram, Program, ProgrammingTarget,
    Project, Simulation, SynthesisProgram, XprProgram,
)
from util import (
    ConfigError, ID_RE, SYMBOL_RE, TIMESCALE_RE, external_path, fpga_config_path, metadata_symbols,
    output_directory, output_name, project_path, read_toml, required_string,
    source_closure, source_order, string_list, task_identifier,
)


FPGA_TEMPLATE = '''# 本地 FPGA 配置；相对路径以项目根目录为基准，也支持绝对路径。
# 必填: Project X-Ray 数据库目录。
xray-database = ""

# 可选: 按列表顺序查找各目录及其 bin/；空列表使用 PATH。
toolchain-root = []

# FPGA 构建必填: Python 模块搜索目录列表，例如 Project X-Ray 源码目录。
PYTHONPATH = []
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


def toolchain_roots(root: Path, data: dict, path: Path) -> tuple[Path, ...]:
    roots = data.get("toolchain-root", [])
    if not isinstance(roots, list) or not all(isinstance(value, str) and value.strip() for value in roots):
        raise ConfigError(
            f'{path}: toolchain-root must be a list of nonempty strings; '
            'use ["path"] for one directory or [] to use PATH'
        )
    return tuple(external_path(root, value) for value in roots)


def load_fpga_config(root: Path, fpga: Fpga) -> Fpga:
    path = fpga_config_path(root, fpga.identifier)
    data = read_toml(path)
    database = data.get("xray-database", "")
    if not isinstance(database, str):
        raise ConfigError(f"{path}: xray-database must be a string; leave it empty if not configured")
    roots = toolchain_roots(root, data, path)
    python_paths = data.get("PYTHONPATH", [])
    if not isinstance(python_paths, list) or not all(
        isinstance(value, str) and value.strip() for value in python_paths
    ):
        raise ConfigError(f'{path}: PYTHONPATH must be a list of nonempty strings; use ["path"]')
    return replace(
        fpga,
        xray_database=external_path(root, database) if database.strip() else None,
        toolchain_roots=roots,
        python_paths=tuple(external_path(root, value) for value in python_paths),
    )


def task_index(data: dict, config_path: Path) -> dict[str, tuple[str, dict, str]]:
    entries: dict[str, tuple[str, dict, str]] = {}
    for kind in ("simulation", "program"):
        raw_entries = data.get(kind, [])
        if not isinstance(raw_entries, list):
            raise ConfigError(f"{config_path}: [[simulation]] and [[program]] must be arrays of tables")
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
        raise ConfigError(f"{config_path}: at least one [[simulation]] or [[program]] is required")
    return entries


def source_index(root: Path, directories: dict,
                 config_path: Path) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    source_dirs = string_list(directories, "sources", str(config_path))
    if not source_dirs:
        raise ConfigError(f"{config_path}: directories.sources must not be empty")
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

    return exports, imports


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


def configure(root: Path, command: str = "script", target_id: str | None = None) -> Project:
    root = root.resolve()
    config_path = root / "configuration.toml"
    data = read_toml(config_path)
    identifier = required_string(data, "id", str(config_path), ID_RE)
    required_string(data, "name", str(config_path))
    entries = task_index(data, config_path)
    full = command in {"aux", "script"}
    cleaning = command in {"clean", "cleandist"}
    all_targets = full or (command in {"clean", "cleandist", "xpr"} and target_id is None)
    if not all_targets:
        expected = ("target id" if cleaning else
                    "simulation" if command in {"build", "simulate"} else "program")
        if target_id not in entries or (not cleaning and entries[target_id][0] != expected):
            raise ConfigError(f"{config_path}: unknown {expected} {target_id!r}")
    selected = entries if all_targets else {target_id: entries[target_id]}
    if command == "xpr":
        selected = {key: entry for key, entry in selected.items() if entry[0] == "program"}
        if not selected:
            raise ConfigError(f"{config_path}: at least one [[program]] is required for xpr")
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

    def constraint_path(raw: dict, location: str) -> Path:
        constraint_dirs = string_list(directories, "constraints", str(config_path))
        if len(constraint_dirs) != 1:
            raise ConfigError(f"{config_path}: directories.constraints must contain one path")
        directory = project_path(root, constraint_dirs[0], f"{config_path}: directories.constraints")
        path = directory / output_name(required_string(raw, "constraints", location), location)
        if not path.is_file():
            raise ConfigError(f"{location}: constraints file does not exist: {path}")
        return path

    needs_fpga = full or (not cleaning and any(kind == "program" for kind, _, _ in selected.values()))
    raw_fpgas = fpga_index(data, config_path) if needs_fpga else {}
    fpgas: dict[str, Fpga] = {}

    def public_fpga(fpga_id: str, location: str) -> Fpga:
        if fpga_id not in raw_fpgas:
            raise ConfigError(f"{location}: unknown fpga id {fpga_id!r}")
        if fpga_id not in fpgas:
            raw, fpga_location = raw_fpgas[fpga_id]
            part = required_string(raw, "part", fpga_location)
            legacy = [key for key in ("xray-database", "toolchain-root", "PYTHONPATH") if key in raw]
            if legacy:
                path = fpga_config_path(root, fpga_id)
                raise ConfigError(f"{fpga_location}: move {', '.join(legacy)} to {path} and remove these fields from configuration.toml")
            fpgas[fpga_id] = Fpga(fpga_id, part, None, (), ())
        return fpgas[fpga_id]

    if full:
        for fpga_id in raw_fpgas:
            public_fpga(fpga_id, str(config_path))

    simulations: list[Simulation] = []
    programs: list[SynthesisProgram | ProgrammingTarget | XprProgram] = []
    cleanup_targets: list[CleanupTarget] = []
    for task_id, (kind, raw, location) in selected.items():
        if cleaning:
            kinds = ("vvp", "vcd") if kind == "simulation" else ("synthesis", "implementation", "bitstream")
            outputs = tuple(output(raw, name, location) for name in kinds)
            if kind == "program":
                frames = outputs[-1].with_suffix(".frames")
                register_output(frames, location)
                outputs = (*outputs, frames)
            suffix = ".f" if kind == "simulation" else ".ys"
            cleanup_targets.append(CleanupTarget(task_id, outputs, root / "build/aux" / f"{task_id}{suffix}"))
            continue
        if kind == "simulation":
            top = required_string(raw, "top-symbol", location, SYMBOL_RE)
            timescale = required_string(raw, "timescale", location, TIMESCALE_RE)
            vvp, vcd = (output(raw, name, location) for name in ("vvp", "vcd"))
            simulations.append(Simulation(task_id, top, timescale, vvp, vcd))
            if full:
                cleanup_targets.append(CleanupTarget(task_id, (vvp, vcd), root / "build/aux" / f"{task_id}.f"))
            continue

        fpga_id = required_string(raw, "fpga", location, ID_RE)
        if command == "program":
            if fpga_id not in raw_fpgas:
                raise ConfigError(f"{location}: unknown fpga id {fpga_id!r}")
            bitstream = output(raw, "bitstream", location)
            local = fpga_config_path(root, fpga_id)
            roots = toolchain_roots(root, read_toml(local), local) if local.exists() or local.is_symlink() else ()
            programs.append(ProgrammingTarget(task_id, bitstream, roots))
            continue

        fpga = public_fpga(fpga_id, location)
        top = required_string(raw, "top-symbol", location, SYMBOL_RE)
        if command == "xpr":
            directory = output_directory(root, directories, "xpr", str(config_path))
            xpr = project_path(root, str(directory / task_id / f"{task_id}.xpr"), location)
            programs.append(XprProgram(task_id, fpga, top, constraint_path(raw, location), xpr))
            continue
        synthesis = output(raw, "synthesis", location)
        if command == "synthesis":
            programs.append(SynthesisProgram(task_id, fpga, top, synthesis))
            continue
        implementation = output(raw, "implementation", location)
        constraints = constraint_path(raw, location)
        if constraints in seen_outputs:
            raise ConfigError(f"{location}: duplicate output {constraints}")
        if command == "implementation":
            programs.append(ImplementationProgram(task_id, fpga, top, synthesis, implementation, constraints))
            continue
        bitstream = output(raw, "bitstream", location)
        frames = bitstream.with_suffix(".frames")
        register_output(frames, location)
        if constraints in (bitstream, frames):
            raise ConfigError(f"{location}: duplicate output {constraints}")
        programs.append(Program(task_id, fpga, top, synthesis, implementation, constraints, bitstream))
        cleanup_targets.append(CleanupTarget(task_id, (synthesis, implementation, frames, bitstream),
                                             root / "build/aux" / f"{task_id}.ys"))

    needs_sources = not cleaning and command != "program"
    exports, imports = source_index(root, directories, config_path) if needs_sources else ({}, {})
    project = Project(
        root, identifier, tuple(simulations), tuple(programs), exports, imports,
        command=command,
        simulation_ids=tuple(key for key, entry in entries.items() if entry[0] == "simulation"),
        program_ids=tuple(key for key, entry in entries.items() if entry[0] == "program"),
        cleanup_targets=tuple(cleanup_targets),
    )
    if needs_sources:
        for target in (*simulations, *programs):
            assert isinstance(target, (Simulation, SynthesisProgram, XprProgram))
            if target.top not in exports:
                kind = "simulation" if isinstance(target, Simulation) else "program"
                raise ConfigError(f"{config_path}: {kind} {target.identifier!r} has no exported top-symbol {target.top!r}")
            source_closure(project, target.top)
        if full:
            for source in imports:
                source_order(project, source)

    # Initialize user-owned settings only after all required public checks pass.
    if command == "xpr":
        return project
    for fpga_id, fpga in fpgas.items():
        if initialize_fpga_config(root, fpga):
            path = fpga_config_path(root, fpga_id)
            print(f"Created {path}; fill xray-database and PYTHONPATH before FPGA builds. "
                  "toolchain-root is optional; use [] to use PATH.", file=sys.stderr)
        fpgas[fpga_id] = load_fpga_config(root, fpga)
    return replace(project, programs=tuple(
        replace(target, fpga=fpgas[target.fpga.identifier]) if isinstance(target, SynthesisProgram) else target
        for target in programs
    ))
