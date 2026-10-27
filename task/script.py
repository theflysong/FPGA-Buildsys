"""Generate the dispatcher and the shell tasks required by this command."""

from __future__ import annotations

from models import ImplementationProgram, Program, ProgrammingTarget, Project, SynthesisProgram
from util import write_executable
from . import bitstream, build, clean, cleandist, implementation, program, simulate, synthesis


def generate_script(project: Project) -> None:
    simulation_cases = "|".join(project.simulation_ids)
    program_cases = "|".join(project.program_ids)
    target_cases = "|".join((*project.simulation_ids, *project.program_ids))
    dispatcher = [
        "#!/usr/bin/env bash", "set -euo pipefail",
        'PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
        "usage() {",
        "  printf '%s\\n' 'Usage: jobs.sh <build|simulate|synthesis|implementation|bitstream> <id>' '       jobs.sh <clean|cleandist> [id]' '       jobs.sh program <id> --protocol <cable> [--busdev-num <bus:device> | --ftdi-serial <serial>]' >&2",
        "  exit 2", "}",
        '[[ "$#" -ge 1 ]] || usage', 'command=$1', 'shift',
        'case "$command" in',
        '  clean|cleandist)',
        '    [[ "$#" -le 1 ]] || usage', '    target=${1:-_project}',
        '    case "$target" in', f'      _project|{target_cases}) ;;',
        '      *) printf "Unknown target id: %s\\n" "$target" >&2; exit 2 ;;',
        '    esac', '    [[ "$#" -eq 0 ]] || shift', '    ;;',
        '  build|simulate)', '    [[ "$#" -eq 1 ]] || usage', '    target=$1', '    shift',
        '    case "$target" in',
        *([f'      {simulation_cases}) ;;'] if simulation_cases else []),
        '      *) printf "Unknown simulation: %s\\n" "$target" >&2; exit 2 ;;',
        '    esac', '    ;;',
        '  synthesis|implementation|bitstream|program)',
        '    [[ "$#" -ge 1 ]] || usage', '    target=$1', '    shift',
        '    [[ "$command" == program || "$#" -eq 0 ]] || usage',
        '    case "$target" in',
        *([f'      {program_cases}) ;;'] if program_cases else []),
        '      *) printf "Unknown project: %s\\n" "$target" >&2; exit 2 ;;',
        '    esac', '    ;;', '  *) usage ;;', 'esac',
        'job_script="$PROJECT_ROOT/build/jobs/$target/$command.sh"',
        '[[ -x "$job_script" ]] || { printf "Missing task script: %s; run buildsys script or the corresponding buildsys target command to regenerate it.\\n" "$job_script" >&2; exit 2; }',
        'exec "$job_script" "$@"',
    ]
    write_executable(project.script, dispatcher)
    if project.command == "script":
        for target_id in (None, *(item.identifier for item in project.cleanup_targets)):
            clean.generate_script(project, target_id)
            cleandist.generate_script(project, target_id)
    for simulation in project.simulations:
        build.generate_script(project, simulation)
        if project.command in {"script", "simulate"}:
            simulate.generate_script(project, simulation)
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
