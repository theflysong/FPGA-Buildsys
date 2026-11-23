"""Export all configured designs and simulations into one Vivado XPR."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil

from models import Project
from util import ConfigError, source_files


def snapshot_path(project: Project) -> Path:
    assert project.xpr is not None
    return project.xpr.parent / ".buildsys" / "model.json"


def model_snapshot(project: Project) -> str:
    """Serialize the model and settings used by export, independent of the command."""
    record = {
        "version": 2,
        "root": project.root.as_posix(),
        "id": project.identifier,
        "projects": [{
            "id": design.identifier, "top": design.top, "part": design.fpga.part,
            "constraints": design.constraints.as_posix(),
        } for design in project.xprs],
        "simulations": [asdict(simulation) for simulation in project.xpr_simulations],
        "hdl": {
            "include_dirs": [path.as_posix() for path in project.hdl.include_dirs],
            "defines": project.hdl.defines,
        },
        "sources": sorted(project.sources),
        "simulation_sources": [source for source in sorted(project.sources)
                               if project.is_simulation_source(source)],
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def ensure_current(project: Project) -> None:
    """Regenerate missing or outdated projects before executing a Vivado stage."""
    assert project.xpr is not None
    if project.xpr.is_file():
        try:
            if snapshot_path(project).read_text(encoding="utf-8") == model_snapshot(project):
                return
        except (FileNotFoundError, UnicodeError):
            pass
    print(f"Regenerating XPR project: {project.xpr}", flush=True)
    execute(project, None)


def tcl_word(value: str | Path) -> str:
    """Quote one Tcl word, including whitespace passed through pytcl."""
    escaped = []
    for character in str(value):
        if character.isspace():
            escaped.append(f"\\u{ord(character):04x}")
        elif character in '\\"$[]':
            escaped.append("\\" + character)
        else:
            escaped.append(character)
    return '"' + "".join(escaped) + '"'


def add_arguments(parser: argparse.ArgumentParser) -> None:
    # Accept solely to provide an actionable migration diagnostic.
    parser.add_argument("target_id", nargs="?", help=argparse.SUPPRESS)


def validate_arguments(arguments: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if arguments.target_id is not None:
        parser.error("xpr no longer takes an xpr-id; run buildsys xpr to export all targets")


def _export(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    from .xpr_stage import _environment

    try:
        from pytcl import Vivado
    except ImportError as exc:
        raise ConfigError("xpr requires pytcl-eda; activate the buildsys .venv or install requirements.txt") from exc
    env = _environment()
    if shutil.which("vivado", path=env.get("PATH")) is None:
        raise ConfigError("Missing tool: vivado; run settings64.bat or add Vivado's bin directory to PATH")
    assert project.xpr is not None
    project.xpr.parent.mkdir(parents=True, exist_ok=True)
    (project.xpr.parent / ".buildsys").mkdir(exist_ok=True)
    # A failed export may leave a partially rewritten XPR. Never reuse its old snapshot.
    snapshot = snapshot_path(project)
    snapshot.unlink(missing_ok=True)
    with Vivado("-log", f".buildsys/xpr-{project.identifier}.log",
                "-journal", f".buildsys/xpr-{project.identifier}.jou",
                nolog=False, nojournal=False, cwd=project.xpr.parent,
                timeout=120, shell=(os.name == "nt"), env=env) as vivado:
        def evaluate(command: str):
            return vivado.eval(tcl_word(command))

        def files(fileset: str, sources: list[str], top: str) -> None:
            for source in sources:
                vivado.add_files("-norecurse", "-fileset", fileset, tcl_word(project.root / source))
            if sources:
                evaluate(f"set_property file_type SystemVerilog "
                         f"[get_files -of_objects [get_filesets {tcl_word(fileset)}]]")
            for key, values in (
                ("include_dirs", [path.as_posix() for path in project.hdl.include_dirs]),
                ("verilog_define", [f"{name}={value}" for name, value in project.hdl.defines]),
            ):
                words = " ".join(tcl_word(value) for value in values)
                evaluate(f"set_property {key} [list {words}] [get_filesets {tcl_word(fileset)}]")
            evaluate(f"set_property top {tcl_word(top)} [get_filesets {tcl_word(fileset)}]")
            vivado.update_compile_order("-fileset", fileset)

        arguments = ["-force", project.identifier, tcl_word(project.xpr.parent)]
        if project.xprs:
            arguments.extend(("-part", tcl_word(project.xprs[0].fpga.part)))
        vivado.create_project(*arguments)
        evaluate("set_property target_language Verilog [current_project]")
        evaluate("set buildsys_synth_flow [get_property FLOW [get_runs synth_1]]")
        evaluate("set buildsys_impl_flow [get_property FLOW [get_runs impl_1]]")
        for design in project.xprs:
            vivado.create_fileset("-srcset", design.source_set)
            files(design.source_set, source_files(project), design.top)
            vivado.create_fileset("-constrset", design.constraint_set)
            vivado.add_files("-norecurse", "-fileset", design.constraint_set, tcl_word(design.constraints))
            evaluate(f"create_run {design.synthesis_run} -flow $buildsys_synth_flow "
                     f"-srcset {design.source_set} -constrset {design.constraint_set} "
                     f"-part {tcl_word(design.fpga.part)}")
            evaluate(f"create_run {design.implementation_run} -flow $buildsys_impl_flow "
                     f"-parent_run {design.synthesis_run} -constrset {design.constraint_set} "
                     f"-part {tcl_word(design.fpga.part)}")
        if project.xprs:
            first = project.xprs[0]
            evaluate(f"current_run -synthesis [get_runs {first.synthesis_run}]")
            evaluate(f"current_run -implementation [get_runs {first.implementation_run}]")
            evaluate("delete_runs [get_runs impl_1]")
            evaluate("delete_runs [get_runs synth_1]")
        evaluate("set_property SOURCE_SET {} [get_filesets sim_1]")
        for simulation in project.xpr_simulations:
            vivado.create_fileset("-simset", simulation.fileset)
            evaluate(f"set_property SOURCE_SET {{}} [get_filesets {simulation.fileset}]")
            files(simulation.fileset, source_files(project, simulation=True), simulation.top)
            evaluate(f"set_property xsim.elaborate.timescale {tcl_word(simulation.timescale)} "
                     f"[get_filesets {simulation.fileset}]")
        if project.xpr_simulations:
            evaluate(f"current_fileset -simset [get_filesets {project.xpr_simulations[0].fileset}]")
            evaluate("delete_fileset [get_filesets sim_1]")
        vivado.close_project()
    if not project.xpr.is_file():
        raise ConfigError(f"Vivado did not create the expected project: {project.xpr}")
    temporary = snapshot.with_suffix(".json.tmp")
    temporary.write_text(model_snapshot(project), encoding="utf-8")
    temporary.replace(snapshot)


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    try:
        from pytcl import TCLError
    except ImportError as exc:
        raise ConfigError("xpr requires pytcl-eda; activate the buildsys .venv or install requirements.txt") from exc
    try:
        _export(project, target_id, task_args, script)
    except TCLError as exc:
        raise ConfigError(f"Vivado xpr export failed: {exc}") from exc
