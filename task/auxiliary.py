"""Generate compiler file lists and synthesis auxiliary files."""

from __future__ import annotations

import shlex

from models import Project, SynthesisProgram
from util import source_closure, yosys_quote


def generate_auxiliary(project: Project) -> None:
    project.auxiliary_dir.mkdir(parents=True, exist_ok=True)
    for simulation in project.simulations:
        lines = [f"# top-symbol: {simulation.top}", "# CLI options: -g2012 -Wall -s <top-symbol>", f"+timescale+{simulation.timescale}"]
        lines.extend(shlex.quote(source) for source in source_closure(project, simulation.top))
        project.filelist(simulation).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for program in project.programs:
        assert isinstance(program, SynthesisProgram)
        sources = source_closure(project, program.top)
        lines = [
            "read_verilog -sv " + " ".join(yosys_quote(source) for source in sources),
            f"synth_xilinx -family xc7 -top {program.top}",
            "check -assert",
            "stat",
            f"hierarchy -top {program.top} -purge_lib",
            "write_json",
        ]
        project.yosys_script(program).write_text("\n".join(lines) + "\n", encoding="utf-8")
