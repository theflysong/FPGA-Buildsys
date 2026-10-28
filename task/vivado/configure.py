"""Resolve Vivado exports and stages without requiring Yosys settings."""

from __future__ import annotations

from pathlib import Path

from models import Project, XprProject, XprSimulation, XprStageTarget
from util import (
    ConfigError, ID_RE, SYMBOL_RE, TIMESCALE_RE, output_directory,
    project_path, required_string, string_list, task_identifier,
)


def selected_xprs(data: dict, config_path: Path, target_id: str | None) -> dict[str, tuple[dict, str]]:
    raw_xprs = data.get("xpr", [])
    if not isinstance(raw_xprs, list):
        raise ConfigError(f"{config_path}: [[xpr]] must be an array of tables")
    xpr_entries: dict[str, tuple[dict, str]] = {}
    for index, raw in enumerate(raw_xprs, 1):
        location = f"{config_path}: xpr[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{location}: expected a table")
        xpr_id = task_identifier(raw, location)
        if xpr_id in xpr_entries:
            raise ConfigError(f"{location}: duplicate xpr id {xpr_id!r}")
        xpr_entries[xpr_id] = (raw, location)
    if target_id is not None:
        if target_id not in xpr_entries:
            raise ConfigError(f"{config_path}: unknown xpr {target_id!r}")
        xpr_entries = {target_id: xpr_entries[target_id]}
    if not xpr_entries:
        raise ConfigError(f"{config_path}: at least one [[xpr]] is required for xpr")
    return xpr_entries


def configure_xpr(root: Path, data: dict, config_path: Path, identifier: str,
                  entries: dict[str, tuple[str, dict, str]], target_id: str | None) -> Project:
    from ..configure import constraint_path, fpga_index, parse_fpga, source_directories

    xpr_entries = selected_xprs(data, config_path, target_id)
    directories = data.get("directories")
    if not isinstance(directories, dict):
        raise ConfigError(f"{config_path}: [directories] is required")
    directory = output_directory(root, directories, "xpr", str(config_path))
    raw_fpgas = fpga_index(data, config_path)
    targets: list[XprProject] = []
    for xpr_id, (raw, location) in xpr_entries.items():
        project_id = required_string(raw, "project", location, ID_RE)
        if project_id not in entries or entries[project_id][0] != "project":
            raise ConfigError(f"{location}: unknown project {project_id!r}")
        _, design, design_location = entries[project_id]
        fpga_id = required_string(design, "fpga", design_location, ID_RE)
        if fpga_id not in raw_fpgas:
            raise ConfigError(f"{design_location}: unknown fpga id {fpga_id!r}")
        fpga_raw, fpga_location = raw_fpgas[fpga_id]
        fpga = parse_fpga(root, fpga_id, fpga_raw, fpga_location)
        top = required_string(design, "top-symbol", design_location, SYMBOL_RE)
        constraints = constraint_path(root, directories, config_path, design, design_location)
        simulation_ids = string_list(raw, "simulations", location) if "simulations" in raw else []
        if len(simulation_ids) != len(set(simulation_ids)):
            raise ConfigError(f"{location}: duplicate simulation reference")
        simulations: list[XprSimulation] = []
        for simulation_id in simulation_ids:
            if simulation_id not in entries or entries[simulation_id][0] != "simulation":
                raise ConfigError(f"{location}: unknown simulation {simulation_id!r}")
            _, simulation, simulation_location = entries[simulation_id]
            simulations.append(XprSimulation(
                simulation_id,
                required_string(simulation, "top-symbol", simulation_location, SYMBOL_RE),
                required_string(simulation, "timescale", simulation_location, TIMESCALE_RE),
            ))
        xpr = project_path(root, str(directory / xpr_id / f"{xpr_id}.xpr"), location)
        targets.append(XprProject(xpr_id, project_id, fpga, top, constraints, tuple(simulations), xpr))
    return Project(root, identifier, (), (), command="xpr", xprs=tuple(targets),
                   source_directories=source_directories(root, directories, config_path),
                   simulation_directories=source_directories(root, directories, config_path, "simulation"))


def configure_xpr_stage(root: Path, data: dict, config_path: Path, identifier: str,
                        entries: dict[str, tuple[str, dict, str]], target_id: str | None,
                        command: str) -> Project:
    """Resolve existing projects without source, constraint, FPGA, or model setup."""
    xpr_entries = selected_xprs(data, config_path, target_id)
    directories = data.get("directories")
    if not isinstance(directories, dict):
        raise ConfigError(f"{config_path}: [directories] is required")
    directory = output_directory(root, directories, "xpr", str(config_path))
    targets: list[XprStageTarget] = []
    for xpr_id, (raw, location) in xpr_entries.items():
        project_id = required_string(raw, "project", location, ID_RE)
        if project_id not in entries or entries[project_id][0] != "project":
            raise ConfigError(f"{location}: unknown project {project_id!r}")
        design = entries[project_id][1]
        simulation_ids = string_list(raw, "simulations", location) if "simulations" in raw else []
        if len(simulation_ids) != len(set(simulation_ids)):
            raise ConfigError(f"{location}: duplicate simulation reference")
        simulations: list[XprSimulation] = []
        for simulation_id in simulation_ids:
            if simulation_id not in entries or entries[simulation_id][0] != "simulation":
                raise ConfigError(f"{location}: unknown simulation {simulation_id!r}")
            # Tops and timescales are already recorded in the exported XPR.
            simulations.append(XprSimulation(simulation_id, "", ""))
        xpr = project_path(root, str(directory / xpr_id / f"{xpr_id}.xpr"), location)
        if not xpr.is_file():
            raise ConfigError(
                f"XPR project does not exist: {xpr}; run buildsys xpr {xpr_id} first"
            )
        top = design.get("top-symbol", "")
        targets.append(XprStageTarget(xpr_id, xpr, top if isinstance(top, str) else "", tuple(simulations)))
    return Project(root, identifier, (), (), command=command, xpr_stages=tuple(targets))


