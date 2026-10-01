"""Generate the project dispatcher and every configured shell task."""

from __future__ import annotations

from models import Project
from util import write_executable
from . import bitstream, build, clean, cleandist, implementation, program, simulate, synthesis


def generate_script(project: Project) -> None:
    simulation_cases = "|".join(item.identifier for item in project.simulations)
    program_cases = "|".join(item.identifier for item in project.programs)
    target_cases = "|".join(item.identifier for item in (*project.simulations, *project.programs))
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
        '      *) printf "Unknown program: %s\\n" "$target" >&2; exit 2 ;;',
        '    esac', '    ;;', '  *) usage ;;', 'esac',
        'job_script="$PROJECT_ROOT/build/jobs/$target/$command.sh"',
        '[[ -x "$job_script" ]] || { printf "Missing task script: %s; run buildsys script to regenerate it.\\n" "$job_script" >&2; exit 2; }',
        'exec "$job_script" "$@"',
    ]
    write_executable(project.script, dispatcher)
    for target_id in (None, *(item.identifier for item in (*project.simulations, *project.programs))):
        clean.generate_script(project, target_id)
        cleandist.generate_script(project, target_id)
    for simulation in project.simulations:
        build.generate_script(project, simulation)
        simulate.generate_script(project, simulation)
    for target in project.programs:
        synthesis.generate_script(project, target)
        implementation.generate_script(project, target)
        bitstream.generate_script(project, target)
        program.generate_script(project, target)
