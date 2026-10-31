"""Execute one configured target inside the existing shared Vivado XPR."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from models import Project, XprStageTarget
from .xpr import tcl_word
from util import ConfigError, write_template


ERROR_LINE = re.compile(r"^\s*(?:ERROR|FATAL)(?:\s*:|\s+\[)", re.IGNORECASE)


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
    try:
        with subprocess.Popen(command, cwd=target.xpr.parent, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace") as process:
            assert process.stdout is not None
            for line in process.stdout:
                if line.strip() == "BUILDSYS_XPR_COMPLETE":
                    completed = True
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
    if log.is_file():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if ERROR_LINE.match(line) and line.strip() not in errors:
                errors.append(line.strip())
    if status or errors or not completed:
        detail = "; ".join(errors[-4:]) or f"exit status {status}, completion={completed}"
        raise ConfigError(f"Vivado xpr-{stage} failed: {detail}; see {log}")
    if stage in {"bitstream", "program"} and (bitstream is None or not bitstream.is_file()):
        raise ConfigError(f"Vivado did not report an existing bitstream; {variables['bitstream_hint']}; see {log}")
    return replace(target, bitstream=bitstream, artifacts=tuple(artifacts))


def execute(project: Project, target_id: str | None,
            task_args: tuple[str, ...] = (), script: Path | None = None) -> Project:
    target = next((item for item in project.xpr_stages if item.identifier == target_id), None)
    if target is None:
        raise ConfigError(f"unknown target {target_id!r}")
    options = dict(zip(task_args[::2], task_args[1::2]))
    target = run_stage(target, project.command.removeprefix("xpr-"),
                       hw_server=options.get("--hw-server", "localhost:3121"),
                       device=options.get("--device", "*"))
    return replace(project, xpr_stages=(target,))
