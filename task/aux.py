"""Generate symbol maps, dependencies, and compiler auxiliary files."""

from __future__ import annotations

import json
import shlex

from models import Project
from util import source_closure, yosys_quote


def generate_aux(project: Project) -> None:
    project.aux_dir.mkdir(parents=True, exist_ok=True)
    (project.aux_dir / f"{project.identifier}.map").write_text(
        json.dumps(project.exports, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (project.aux_dir / f"{project.identifier}.dep").write_text(
        json.dumps(project.imports, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for simulation in project.simulations:
        lines = [f"# top-symbol: {simulation.top}", "# CLI options: -g2012 -Wall -s <top-symbol>", f"+timescale+{simulation.timescale}"]
        lines.extend(shlex.quote(source) for source in source_closure(project, simulation.top))
        project.filelist(simulation).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for program in project.programs:
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
