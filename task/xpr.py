"""Export one [[xpr]] target, or all targets, with its design and simulations."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

from models import Project
from util import ConfigError, add_optional_target_argument as add_arguments, source_closure


def tcl_word(value: str | Path) -> str:
    """Quote one Tcl word, including whitespace pytcl would otherwise re-wrap.

    pytcl 0.3 passes strings without whitespace verbatim to Tcl. Escaping
    whitespace as Unicode keeps this quoted word intact through its serializer.
    """
    escaped = []
    for character in str(value):
        if character.isspace():
            escaped.append(f"\\u{ord(character):04x}")
        elif character in '\\"$[]':
            escaped.append("\\" + character)
        else:
            escaped.append(character)
    return '"' + "".join(escaped) + '"'


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    try:
        from pytcl import Vivado
    except ImportError as exc:
        raise ConfigError(
            "xpr requires pytcl-eda; activate the buildsys .venv or install requirements.txt "
            "with the Python interpreter running buildsys"
        ) from exc
    if shutil.which("vivado") is None:
        raise ConfigError(
            "Missing tool: vivado; add Vivado's bin directory to PATH "
            "using settings64.bat on Windows or source settings64.sh on Linux"
        )

    env = os.environ.copy()
    if os.name == "nt":
        # Vivado's Tcl cannot execute Microsoft Store's Python app aliases.
        # Let pytcl's bridge fall back to the interpreter running buildsys.
        aliases = os.path.normcase(os.path.join(env.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps"))
        paths = [path for path in env.get("PATH", "").split(os.pathsep)
                 if os.path.normcase(os.path.normpath(path.strip('"'))) != aliases]
        env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), *paths])

    for target in project.xprs:
        target.xpr.parent.mkdir(parents=True, exist_ok=True)
        # Windows needs cmd.exe to resolve pytcl's bare "vivado" to vivado.bat.
        with Vivado(cwd=target.xpr.parent, timeout=120, shell=(os.name == "nt"), env=env) as vivado:
            vivado.create_project("-force", target.identifier, tcl_word(target.xpr.parent),
                                  "-part", tcl_word(target.fpga.part))
            design_closure = source_closure(project, target.top)
            simulation_closures = {
                simulation.identifier: source_closure(project, simulation.top) for simulation in target.simulations
            }
            # Directory membership determines ownership, even for dependencies
            # referenced only by a testbench.
            design_sources = list(dict.fromkeys(
                source for sources in (design_closure, *simulation_closures.values()) for source in sources
                if not project.is_simulation_source(source)
            ))
            for source in design_sources:
                vivado.add_files("-norecurse", "-fileset", "sources_1", tcl_word(project.root / source))
            simulation_dependencies = {source for sources in simulation_closures.values() for source in sources}
            # SOURCE_SET supplies design dependencies. Disable unrelated design
            # files for simulation so the design top is not compiled implicitly.
            for source in design_sources:
                enabled = "true" if source in simulation_dependencies else "false"
                vivado.eval(tcl_word(
                    f"set_property USED_IN_SIMULATION {enabled} "
                    f"[get_files -of_objects [get_filesets sources_1] {tcl_word(project.root / source)}]"
                ))
            vivado.add_files("-norecurse", "-fileset", "constrs_1", tcl_word(target.constraints))
            # Keep Vivado object handles in Tcl; Python round trips lose their type.
            vivado.eval(tcl_word(f"set_property top {tcl_word(target.top)} [get_filesets sources_1]"))
            vivado.eval(tcl_word("set_property target_language Verilog [current_project]"))
            # Match the SystemVerilog support used by iverilog -g2012 and yosys -sv.
            vivado.eval(tcl_word(
                "set_property file_type SystemVerilog [get_files -of_objects [get_filesets sources_1]]"
            ))
            vivado.update_compile_order("-fileset", "sources_1")
            # Detach the unused default simulation; configured simulations link
            # to design sources and own only files from simulation directories.
            vivado.eval(tcl_word("set_property SOURCE_SET {} [get_filesets sim_1]"))
            for simulation in target.simulations:
                fileset = f"sim_{simulation.identifier}"
                vivado.create_fileset("-simset", tcl_word(fileset))
                vivado.eval(tcl_word(f"set_property SOURCE_SET sources_1 [get_filesets {tcl_word(fileset)}]"))
                simulation_sources = [source for source in simulation_closures[simulation.identifier]
                                      if project.is_simulation_source(source)]
                for source in simulation_sources:
                    vivado.add_files("-norecurse", "-fileset", fileset, tcl_word(project.root / source))
                vivado.eval(tcl_word(
                    f"set_property top {tcl_word(simulation.top)} [get_filesets {tcl_word(fileset)}]"
                ))
                vivado.eval(tcl_word(
                    f"set_property xsim.elaborate.timescale {tcl_word(simulation.timescale)} "
                    f"[get_filesets {tcl_word(fileset)}]"
                ))
                if simulation_sources:
                    vivado.eval(tcl_word(
                        f"set_property file_type SystemVerilog [get_files -of_objects [get_filesets {tcl_word(fileset)}]]"
                    ))
                vivado.update_compile_order("-fileset", fileset)
            if target.simulations:
                vivado.eval(tcl_word(
                    f"current_fileset -simset [get_filesets {tcl_word('sim_' + target.simulations[0].identifier)}]"
                ))
                # Vivado cannot delete an active fileset; switch to the requested one first.
                vivado.eval(tcl_word("delete_fileset [get_filesets sim_1]"))
            vivado.close_project()
        if not target.xpr.is_file():
            raise ConfigError(f"Vivado did not create the expected project: {target.xpr}")
        print(f"Created {target.xpr}", flush=True)
