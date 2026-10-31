"""Generate and execute the Yosys synthesis task for one FPGA program."""

from __future__ import annotations

from pathlib import Path
import shlex
from artifacts import shell_report, target_artifacts

from models import Project, SynthesisProgram
from util import (
    BUILDSYS_DIR, add_target_argument as add_arguments,
    execute_job, program_header, relative, render_template, write_template,
    require_fpga_build as validate,
)


def generate_script(project: Project, program: SynthesisProgram) -> None:
    job_dir = project.job_dir(program)
    synthesis = relative(project, program.synthesis)
    yosys_script = relative(project, project.yosys_script(program))
    json_compactor = str(BUILDSYS_DIR / "compact_json.py")
    write_template(
        job_dir / "synthesis.sh", "yosys/synthesis.sh", executable=True,
        header="\n".join(program_header(project, program)), yosys_script=shlex.quote(yosys_script),
        output_directory=shlex.quote(relative(project, program.synthesis.parent)),
        tmpfs_check=render_template("shell/tmpfs-check.sh").rstrip("\n"),
        log_directory=shlex.quote(f"/dev/shm/buildsys-{project.identifier}-{program.identifier}-synthesis-XXXXXX"),
        program_id=program.identifier, json_compactor=shlex.quote(json_compactor),
        synthesis=shlex.quote(synthesis),
        report=shell_report(project, target_artifacts(program, stage="synthesis")),
    )


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    execute_job(project, "synthesis", target_id, task_args, script)
