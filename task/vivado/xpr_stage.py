"""Keep the shared Vivado XPR current and execute one configured target."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from models import Project, XprStageTarget
from .xpr import ensure_current, tcl_word
from util import ConfigError, write_template


ERROR_LINE = re.compile(r"^\s*(?:ERROR|FATAL)(?:\s*:|\s+\[)", re.IGNORECASE)
SOURCE_LOCATION = re.compile(r":\d+(?::\d+)?\]$")
RUN_LOGS = ("*.vds", "*.vdi", "runme.log")
SIMULATION_LOGS = ("xvlog.log", "xvhdl.log", "compile.log", "elaborate.log", "simulate.log")


def _log_errors(path: Path, since_ns: int = 0) -> list[str]:
    try:
        if path.stat().st_mtime_ns >= since_ns:
            with path.open(encoding="utf-8", errors="replace") as stream:
                return [line.strip() for line in stream if ERROR_LINE.match(line)]
    except OSError:
        pass
    return []


def _failure_detail(errors: list[str], status: int, completed: bool, log: Path,
                    diagnostic_directory: Path | None, since_ns: int, *, simulation: bool) -> str:
    diagnostics: list[str] = []
    logs: list[Path] = []
    if diagnostic_directory is not None:
        patterns = SIMULATION_LOGS if simulation else RUN_LOGS
        try:
            paths = [path for pattern in patterns for path in sorted(diagnostic_directory.glob(pattern))]
        except OSError:
            paths = []
        for path in paths:
            if messages := _log_errors(path, since_ns):
                diagnostics.extend(messages)
                logs.append(path)
    messages = sorted(dict.fromkeys([*diagnostics, *errors]), key=lambda line: SOURCE_LOCATION.search(line) is None)
    detail = messages[:4] or [f"exit status {status}, completion={completed}"]
    return "\n  ".join([*detail, *(f"See {path}" for path in [*logs, log])])


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt":
        aliases = os.path.normcase(os.path.join(env.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps"))
        paths = [path for path in env.get("PATH", "").split(os.pathsep)
                 if os.path.normcase(os.path.normpath(path.strip('"'))) != aliases]
        env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), *paths])
    return env


def run_stage(target: XprStageTarget, stage: str, *,
              hw_server: str = "localhost:3121", device: str = "*") -> XprStageTarget:
    if not target.xpr.is_file():
        raise ConfigError(f"XPR project does not exist: {target.xpr}; run buildsys xpr first")
    env = _environment()
    executable = shutil.which("vivado", path=env.get("PATH"))
    if executable is None:
        raise ConfigError("Missing tool: vivado; run settings64.bat or add Vivado's bin directory to PATH")
    directory = target.xpr.parent / ".buildsys"
    directory.mkdir(exist_ok=True)
    stem = f"{stage}-{target.identifier}"
    script, log, journal = (directory / f"{stem}.{extension}" for extension in ("tcl", "log", "jou"))
    variables = {
        "xpr": target.xpr.as_posix(), "stage": stage, "target_kind": target.kind,
        "synthesis_run": target.synthesis_run, "implementation_run": target.implementation_run,
        "fileset": target.fileset, "hw_server": hw_server, "device_pattern": device,
        "simulation_directory": (target.xpr.with_suffix(".sim") / target.fileset / "behav" / "xsim").as_posix(),
        "bitstream_hint": f"run buildsys xpr-bitstream {target.identifier} first",
    }
    write_template(script, "vivado/xpr-stage.tcl",
                   **{key: tcl_word(value) for key, value in variables.items()})
    command = [executable, "-mode", "batch", "-notrace", "-source", str(script),
               "-log", str(log), "-journal", str(journal)]
    errors: list[str] = []
    completed = False
    bitstream: Path | None = None
    artifacts: list[tuple[str, Path]] = []
    diagnostic_directory = Path(variables["simulation_directory"]) if stage == "simulation" else None
    started_ns = diagnostic_since_ns = time.time_ns()
    try:
        with subprocess.Popen(command, cwd=target.xpr.parent, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace") as process:
            assert process.stdout is not None
            for line in process.stdout:
                if line.strip() == "BUILDSYS_XPR_COMPLETE":
                    completed = True
                elif line.startswith("BUILDSYS_FAILED_RUN_LOGS "):
                    started, _, path = line.removeprefix("BUILDSYS_FAILED_RUN_LOGS ").rstrip("\r\n").partition(" ")
                    if started.isdecimal() and path:
                        diagnostic_since_ns = int(started) * 1_000_000
                        diagnostic_directory = target.xpr.parent / path
                elif line.startswith("BUILDSYS_BITSTREAM "):
                    bitstream = Path(line[len("BUILDSYS_BITSTREAM "):].strip())
                    artifacts.append(("bitstream", bitstream))
                elif line.startswith("BUILDSYS_ARTIFACT "):
                    kind, _, value = line[len("BUILDSYS_ARTIFACT "):].strip().partition(" ")
                    label = {"synthesis": "synthesis run directory", "implementation": "implementation run directory",
                             "simulation": "simulation directory"}.get(kind, kind)
                    artifacts.append((label, Path(value)))
                else:
                    print(line, end="", flush=True)
                if ERROR_LINE.match(line):
                    errors.append(line.strip())
            status = process.wait()
    except OSError as exc:
        raise ConfigError(f"Cannot start Vivado: {exc}; script retained at {script}") from exc
    errors.extend(_log_errors(log, started_ns))
    if status or errors or not completed:
        detail = _failure_detail(errors, status, completed, log, diagnostic_directory,
                                 diagnostic_since_ns, simulation=stage == "simulation")
        raise ConfigError(f"Vivado xpr-{stage} failed:\n  {detail}")
    if stage in {"bitstream", "program"} and (bitstream is None or not bitstream.is_file()):
        raise ConfigError(f"Vivado did not report an existing bitstream; {variables['bitstream_hint']}; see {log}")
    return replace(target, bitstream=bitstream, artifacts=tuple(artifacts))


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> Project:
    target = next((item for item in project.xpr_stages if item.identifier == target_id), None)
    if target is None:
        raise ConfigError(f"unknown target {target_id!r}")
    ensure_current(project)
    options = dict(zip(task_args[::2], task_args[1::2]))
    target = run_stage(target, project.command.removeprefix("xpr-"),
                       hw_server=options.get("--hw-server", "localhost:3121"),
                       device=options.get("--device", "*"))
    return replace(project, xpr_stages=(target,))
