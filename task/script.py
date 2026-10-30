"""Generate the dispatcher and the shell tasks required by this command."""

from __future__ import annotations

import shlex

from models import Project
from util import BUILDSYS_DIR, write_executable
from . import build, clean, cleandist, simulate


def generate_script(project: Project) -> None:
    simulation_cases = "|".join(project.simulation_ids)
    program_cases = "|".join(project.program_ids)
    target_cases = "|".join(("_project", *project.simulation_ids, *project.program_ids))
    dispatcher = [
        "#!/usr/bin/env bash", "set -euo pipefail",
        'PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"',
        'cd "$PROJECT_ROOT"',
        "usage() {",
        "  printf '%s\\n' 'Usage: jobs.sh <build|simulate> <simulation-id>' '       jobs.sh [yosys-]<synthesis|implementation|bitstream|program> <id> [options]' '       jobs.sh <clean|cleandist> [id]' 'FPGA stages use the selected toolchain; program options match buildsys program --help.' >&2",
        "  exit 2", "}",
        '[[ "$#" -ge 1 ]] || usage', 'command=$1', 'shift',
        'case "$command" in',
        '  synthesis|implementation|bitstream|program)',
        f'    command=$(python3 {shlex.quote(str(BUILDSYS_DIR / "toolchains.py"))} . --resolve "$command")',
        '    ;;', 'esac',
        'case "$command" in',
        '  xpr-synthesis|xpr-implementation|xpr-bitstream|xpr-program)',
        f'    exec python3 {shlex.quote(str(BUILDSYS_DIR / "main.py"))} --project . "$command" "$@"',
        '    ;;',
        '  yosys-synthesis|yosys-implementation|yosys-bitstream|yosys-program) command=${command#yosys-} ;;',
        'esac',
        'case "$command" in',
        '  clean|cleandist)',
        '    [[ "$#" -le 1 ]] || usage', '    target=${1:-_project}',
        '    case "$target" in', f'      {target_cases}) ;;',
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
    if project.toolchain == "yosys":
        from .yosys.script import generate_script as generate_yosys_script
        generate_yosys_script(project)
