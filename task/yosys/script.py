"""Generate tasks for the selected Yosys backend."""

from models import ImplementationProgram, Program, ProgrammingTarget, Project, SynthesisProgram
from . import bitstream, implementation, program, synthesis


def generate_script(project: Project) -> None:
    for target in project.programs:
        if isinstance(target, SynthesisProgram):
            synthesis.generate_script(project, target)
        if isinstance(target, ImplementationProgram):
            implementation.generate_script(project, target)
        if isinstance(target, Program):
            bitstream.generate_script(project, target)
            if project.command == "script":
                program.generate_script(project, ProgrammingTarget(
                    target.identifier, target.bitstream, target.fpga.toolchain_roots,
                ))
        if isinstance(target, ProgrammingTarget):
            program.generate_script(project, target)
