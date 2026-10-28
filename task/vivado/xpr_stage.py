"""Execute stages of an existing XPR through a native Vivado batch Tcl session."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from models import Project, XprSimulation, XprStageTarget
from .xpr import tcl_word
from util import ConfigError


ERROR_LINE = re.compile(r"^\s*(?:ERROR|FATAL)(?:\s*:|\s+\[)", re.IGNORECASE)
TCL_HELPER = Path(__file__).with_name("vivado_xpr.tcl")


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt":
        aliases = os.path.normcase(os.path.join(
            env.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps"
        ))
        paths = [path for path in env.get("PATH", "").split(os.pathsep)
                 if os.path.normcase(os.path.normpath(path.strip('"'))) != aliases]
        env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), *paths])
    return env


def _target(project: Project, target_id: str | None) -> XprStageTarget:
    for target in project.xpr_stages:
        if target.xpr_id == target_id:
            # Check again before starting a tool; never create a missing project.
            if not target.xpr.is_file():
                raise ConfigError(
                    f"XPR project does not exist: {target.xpr}; "
                    f"run buildsys xpr {target.xpr_id} first"
                )
            return target
    raise ConfigError(f"unknown xpr {target_id!r}")


def _simulation(target: XprStageTarget, simulation_id: str | None) -> XprSimulation:
    if not target.simulations:
        raise ConfigError(f"XPR {target.xpr_id!r} has no configured simulations")
    if simulation_id is None:
        return target.simulations[0]
    for simulation in target.simulations:
        if simulation.identifier == simulation_id:
            return simulation
    raise ConfigError(f"simulation {simulation_id!r} does not belong to xpr {target.xpr_id!r}")


def run_stage(target: XprStageTarget, stage: str, *, simulation: XprSimulation | None = None,
              hw_server: str = "localhost:3121", device: str = "*") -> XprStageTarget:
    """Retain the script, logs, and native Vivado outputs beside the XPR.

    No Python/Tcl bridge is needed: all run dependencies and hardware operations
    execute inside one Tcl session. A completion marker also detects Tcl errors
    for Vivado versions that exit with status zero after a source error.
    """
    env = _environment()
    executable = shutil.which("vivado", path=env.get("PATH"))
    if executable is None:
        raise ConfigError("Missing tool: vivado; run settings64.bat or add Vivado's bin directory to PATH")
    directory = target.xpr.parent / ".buildsys"
    directory.mkdir(exist_ok=True)
    stem = stage + ("-" + simulation.identifier if simulation else "")
    script = directory / f"{stem}.tcl"
    log = directory / f"{stem}.log"
    journal = directory / f"{stem}.jou"
    variables = {
        "xpr": target.xpr.as_posix(), "stage": stage,
        "synthesis_run": target.synthesis_run, "implementation_run": target.implementation_run,
        "fileset": simulation.fileset if simulation else "",
        "hw_server": hw_server, "device_pattern": device,
        "bitstream_hint": f"run buildsys xpr-bitstream {target.xpr_id} first",
    }
    script.write_text(
        "namespace eval buildsys {}\n" +
        "".join(f"set ::buildsys::{key} {tcl_word(value)}\n" for key, value in variables.items()) +
        TCL_HELPER.read_text(encoding="utf-8"), encoding="utf-8",
    )
    command = [executable, "-mode", "batch", "-notrace", "-source", str(script),
               "-log", str(log), "-journal", str(journal)]
    # Popen resolves native .bat launchers on Windows without another shell
    # command string; all user values are safely encoded inside the Tcl file.
    errors: list[str] = []
    completed = False
    bitstream: Path | None = None
    try:
        with subprocess.Popen(command, cwd=target.xpr.parent, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace") as process:
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                if ERROR_LINE.match(line):
                    errors.append(line.strip())
                if line.strip() == "BUILDSYS_XPR_COMPLETE":
                    completed = True
                if line.startswith("BUILDSYS_BITSTREAM "):
                    bitstream = Path(line[len("BUILDSYS_BITSTREAM "):].strip())
            status = process.wait()
    except OSError as exc:
        raise ConfigError(f"Cannot start Vivado: {exc}; script retained at {script}") from exc
    if log.is_file():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if ERROR_LINE.match(line) and line.strip() not in errors:
                errors.append(line.strip())
    if status or errors or not completed:
        detail = "; ".join(errors[-4:]) or f"exit status {status}, completion={completed}"
        raise ConfigError(f"Vivado xpr-{stage} failed: {detail}; see {log}")
    if stage in {"bitstream", "program"}:
        if bitstream is None or not bitstream.is_file():
            raise ConfigError(f"Vivado did not report an existing bitstream; {variables['bitstream_hint']}; see {log}")
        print(f"Bitstream: {bitstream}", flush=True)
    return replace(target, bitstream=bitstream)


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> Project:
    target = _target(project, target_id)
    stage = project.command.removeprefix("xpr-")
    if stage == "simulation":
        simulation = _simulation(target, task_args[0] if task_args else None)
        target = run_stage(target, stage, simulation=simulation)
    elif stage == "program":
        options = dict(zip(task_args[::2], task_args[1::2]))
        target = run_stage(target, stage, hw_server=options.get("--hw-server", "localhost:3121"),
                           device=options.get("--device", "*"))
    else:
        target = run_stage(target, stage)
    return replace(project, xpr_stages=tuple(
        target if item.xpr_id == target.xpr_id else item for item in project.xpr_stages
    ))
