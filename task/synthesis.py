"""Generate and execute the synthesis task for one FPGA program."""

from __future__ import annotations

from pathlib import Path
import shlex

from models import Program, Project
from util import (
    BUILDSYS_DIR, TMPFS_CHECK, add_target_argument as add_arguments,
    execute_job, program_header, relative, write_executable,
    require_fpga_build as validate,
)


def generate_script(project: Project, program: Program) -> None:
    job_dir = project.job_dir(program)
    header = program_header(project, program)
    synthesis = relative(project, program.synthesis)
    yosys_script = relative(project, project.yosys_script(program))
    json_compactor = str(BUILDSYS_DIR / "compact_json.py")
    write_executable(job_dir / "synthesis.sh", [
        *header,
        f"yosys_script={shlex.quote(yosys_script)}",
        '[[ -f "$yosys_script" ]] || { printf "Missing %s; run the Python aux command first.\\n" "$yosys_script" >&2; exit 2; }',
        'command -v yosys >/dev/null || { printf "Missing tool: yosys\\n" >&2; exit 127; }',
        f"mkdir -p -- {shlex.quote(relative(project, program.synthesis.parent))}",
        TMPFS_CHECK,
        f'log_dir=$(mktemp -d -- /dev/shm/buildsys-{project.identifier}-{program.identifier}-synthesis-XXXXXX)',
        f'synth_log="$log_dir/{program.identifier}.synthesis.log"',
        'printf "Synthesis log: %s\\n" "$synth_log" >&2',
        f"json_compactor={shlex.quote(json_compactor)}",
        'if ! yosys -Q -q -l "$synth_log" -s "$yosys_script" | python3 "$json_compactor" '
        + shlex.quote(synthesis) + '; then',
        f"  rm -f -- {shlex.quote(synthesis)}",
        '  exit 1',
        'fi',
    ])


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "synthesis", target_id, task_args, script)
