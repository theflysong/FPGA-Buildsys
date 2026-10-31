"""Resolve the workspace's one Vivado project and its configured targets."""

from pathlib import Path

from layout import Layout
from models import Project, XprProject, XprSimulation, XprStageTarget
from util import ConfigError, ID_RE, SYMBOL_RE, TIMESCALE_RE, required_string


def configure_xpr(root: Path, data: dict, config_path: Path, identifier: str,
                  entries: dict[str, tuple[str, dict, str]], target_id: str | None) -> Project:
    from ..configure import constraint_path, fpga_index, parse_fpga, source_directories

    if target_id is not None:
        raise ConfigError("xpr no longer takes an xpr-id; run buildsys xpr to export all targets")
    directories = data.get("directories")
    if not isinstance(directories, dict):
        raise ConfigError(f"{config_path}: [directories] is required")
    raw_fpgas = fpga_index(data, config_path) if any(kind == "project" for kind, _, _ in entries.values()) else {}
    designs: list[XprProject] = []
    simulations: list[XprSimulation] = []
    for target_id, (kind, raw, location) in entries.items():
        top = required_string(raw, "top-symbol", location, SYMBOL_RE)
        if kind == "simulation":
            timescale = required_string({"timescale": "1ns/1ps", **raw}, "timescale", location, TIMESCALE_RE)
            simulations.append(XprSimulation(target_id, top, timescale))
        else:
            fpga_id = required_string(raw, "fpga", location, ID_RE)
            if fpga_id not in raw_fpgas:
                raise ConfigError(f"{location}: unknown fpga id {fpga_id!r}")
            fpga_raw, fpga_location = raw_fpgas[fpga_id]
            designs.append(XprProject(target_id, parse_fpga(root, fpga_id, fpga_raw, fpga_location), top,
                                      constraint_path(root, directories, config_path, raw, location)))
    return Project(root, identifier, (), (), command="xpr", xprs=tuple(designs),
                   xpr_simulations=tuple(simulations), xpr=Layout(root).xpr(identifier),
                   source_directories=source_directories(root, directories, config_path),
                   simulation_directories=source_directories(root, directories, config_path, "simulation"))


def configure_xpr_stage(root: Path, data: dict, config_path: Path, identifier: str,
                        entries: dict[str, tuple[str, dict, str]], target_id: str | None,
                        command: str) -> Project:
    """Existing XPR commands need ids, not sources, constraints, or local settings."""
    kind = "simulation" if command == "xpr-simulation" else "project"
    if target_id not in entries or entries[target_id][0] != kind:
        raise ConfigError(f"{config_path}: unknown {kind} {target_id!r}; "
                          f"{command} now takes a {kind}-id, not an xpr-id")
    xpr = Layout(root).xpr(identifier)
    if not xpr.is_file():
        raise ConfigError(f"XPR project does not exist: {xpr}; run buildsys xpr first")
    target = XprStageTarget(target_id, xpr, kind)
    return Project(root, identifier, (), (), command=command, xpr=xpr, xpr_stages=(target,))
