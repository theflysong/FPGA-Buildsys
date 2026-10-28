"""Generate compiler file lists and synthesis auxiliary files."""

from __future__ import annotations

import shlex

from models import Project
from util import source_closure


def generate_auxiliary(project: Project) -> None:
    project.auxiliary_dir.mkdir(parents=True, exist_ok=True)
    for simulation in project.simulations:
        lines = [f"# top-symbol: {simulation.top}", "# CLI options: -g2012 -Wall -s <top-symbol>", f"+timescale+{simulation.timescale}"]
        lines.extend(shlex.quote(source) for source in source_closure(project, simulation.top))
        project.filelist(simulation).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if project.toolchain == "yosys":
        from .yosys.auxiliary import generate_auxiliary as generate_yosys_auxiliary
        generate_yosys_auxiliary(project)
