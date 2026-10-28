"""Generate Yosys synthesis scripts from the shared source model."""

from models import Project, SynthesisProgram
from util import source_closure, yosys_quote


def generate_auxiliary(project: Project) -> None:
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
