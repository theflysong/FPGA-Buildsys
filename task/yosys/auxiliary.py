"""Generate Yosys synthesis scripts from the shared source model."""

from models import Project, SynthesisProgram
from util import source_closure, write_template, yosys_quote


def generate_auxiliary(project: Project) -> None:
    for program in project.programs:
        assert isinstance(program, SynthesisProgram)
        sources = source_closure(project, program.top)
        write_template(project.yosys_script(program), "yosys/synthesis.ys",
                       sources=" ".join(yosys_quote(source) for source in sources), top=program.top)
