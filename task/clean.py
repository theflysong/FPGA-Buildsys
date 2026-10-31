"""Clean owned products, resetting only the selected targets in a shared XPR."""

from __future__ import annotations

from pathlib import Path
import re
import shlex
import shutil

from layout import Layout
from models import Project, XprStageTarget
from util import (
    BUILDSYS_DIR, ConfigError, add_optional_target_argument as add_arguments,
    selected_targets, selected_targets as validate, task_header, write_executable,
)


def remove_owned(project: Project, path: Path) -> None:
    """Resolve every deletion before acting; never follow an escaped symlink."""
    root = project.root.resolve()
    managed = tuple(root / "build" / name for name in
                    ("icarus", "yosys", "vivado", "model", "symbol", "auxiliary", "jobs"))
    resolved = path.resolve()
    if path == project.script and resolved == root / "jobs.sh":
        path.unlink(missing_ok=True)
        return
    if not any(resolved.is_relative_to(directory) for directory in managed):
        raise ConfigError(f"Refusing to delete outside managed build directories: {path} -> {resolved}")
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def cleanup_script(project: Project, target_id: str | None, *, dist: bool,
                   temporary: bool = False) -> list[str]:
    command = "cleandist" if dist else "clean"
    arguments = " " + shlex.quote(target_id) if target_id is not None else ""
    return [*task_header(project, temporary=temporary),
            f'exec python3 {shlex.quote(str(BUILDSYS_DIR / "main.py"))} '
            f'--project "$PROJECT_ROOT" {command}{arguments}']


def generate_script(project: Project, target_id: str | None) -> None:
    directory = project.root / "build/jobs" / (target_id or "_project")
    write_executable(directory / "clean.sh", cleanup_script(project, target_id, dist=False))


def cleanup(project: Project, target_id: str | None, *, dist: bool) -> None:
    targets = selected_targets(project, target_id)
    layout = Layout(project.root)
    if dist and target_id is None:
        # Removing a whole generated workspace does not require Vivado.
        for name in ("icarus", "yosys", "vivado", "auxiliary", "model", "symbol", "jobs"):
            remove_owned(project, project.root / "build" / name)
        remove_owned(project, project.script)
        return
    xpr = layout.xpr(project.identifier)
    if xpr.is_file():
        from .vivado.xpr_stage import run_stage
        for target in targets:
            run_stage(XprStageTarget(target.identifier, xpr, target.kind), "clean")
    for target in targets:
        backend = "icarus" if target.kind == "simulation" else "yosys"
        remove_owned(project, layout.path(backend, target.identifier))
        if dist:
            remove_owned(project, target.auxiliary)
            remove_owned(project, project.job_dir(target))
            for stage in ("simulation", "synthesis", "implementation", "bitstream", "program", "clean"):
                directory = xpr.parent / ".buildsys"
                for path in directory.glob(f"{stage}-{target.identifier}*"):
                    suffix = path.name.removeprefix(f"{stage}-{target.identifier}")
                    if suffix in {".tcl", ".log", ".jou"} or re.fullmatch(r"_\d+\.backup\.(log|jou)", suffix):
                        remove_owned(project, path)


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> None:
    cleanup(project, target_id, dist=False)
