"""Generate the dispatcher and the shell tasks required by this command."""

from __future__ import annotations

import shlex

from models import Project
from util import BUILDSYS_DIR, write_template
from . import build, clean, cleandist, simulate


def generate_script(project: Project) -> None:
    simulation_cases = "|".join(project.simulation_ids)
    program_cases = "|".join(project.program_ids)
    target_cases = "|".join(("_project", *project.simulation_ids, *project.program_ids))
    write_template(
        project.script, "dispatcher.sh", executable=True,
        toolchains=shlex.quote(str(BUILDSYS_DIR / "toolchains.py")),
        main=shlex.quote(str(BUILDSYS_DIR / "main.py")), target_cases=target_cases,
        simulation_cases=f"      {simulation_cases}) ;;" if simulation_cases else "",
        program_cases=f"      {program_cases}) ;;" if program_cases else "",
    )
    if project.command == "script":
        for target_id in (None, *(item.identifier for item in project.cleanup_targets)):
            clean.generate_script(project, target_id)
            cleandist.generate_script(project, target_id)
    for simulation in project.simulations:
        build.generate_script(project, simulation)
        if project.command in {"script", "simulate"}:
            simulate.generate_script(project, simulation)
    if project.toolchain == "yosys":
        from .yosys.script import generate_script as generate_yosys_script
        generate_yosys_script(project)
