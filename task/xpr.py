"""Create Vivado projects for one program, or all programs when no id is given."""

from __future__ import annotations

from pathlib import Path
import shutil

from models import Project, XprProgram
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
        raise ConfigError("Missing tool: vivado; source Vivado settings64.sh to add it to PATH")

    for target in project.programs:
        assert isinstance(target, XprProgram)
        target.xpr.parent.mkdir(parents=True, exist_ok=True)
        with Vivado(cwd=target.xpr.parent, timeout=120) as vivado:
            vivado.create_project("-force", target.identifier, tcl_word(target.xpr.parent),
                                  "-part", tcl_word(target.fpga.part))
            for source in source_closure(project, target.top):
                vivado.add_files("-norecurse", "-fileset", "sources_1", tcl_word(project.root / source))
            vivado.add_files("-norecurse", "-fileset", "constrs_1", tcl_word(target.constraints))
            vivado.set_property("top", tcl_word(target.top), vivado.get_filesets("sources_1"))
            vivado.set_property("target_language", "Verilog", vivado.current_project())
            # Match the SystemVerilog support used by iverilog -g2012 and yosys -sv.
            vivado.eval(tcl_word(
                "set_property file_type SystemVerilog [get_files -of_objects [get_filesets sources_1]]"
            ))
            vivado.update_compile_order("-fileset", "sources_1")
            vivado.close_project()
        if not target.xpr.is_file():
            raise ConfigError(f"Vivado did not create the expected project: {target.xpr}")
        print(f"Created {target.xpr}", flush=True)
