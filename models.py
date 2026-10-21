"""Project configuration data shared by the planner and tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Simulation:
    identifier: str
    top: str
    timescale: str
    vvp: Path
    vcd: Path


@dataclass(frozen=True)
class Fpga:
    identifier: str
    part: str
    xray_database: Path | None
    toolchain_roots: tuple[Path, ...]
    python_paths: tuple[Path, ...]


@dataclass(frozen=True)
class SynthesisProgram:
    identifier: str
    fpga: Fpga
    top: str
    synthesis: Path


@dataclass(frozen=True)
class ImplementationProgram(SynthesisProgram):
    implementation: Path
    constraints: Path


@dataclass(frozen=True)
class Program(ImplementationProgram):
    bitstream: Path

    @property
    def frames(self) -> Path:
        return self.bitstream.with_suffix(".frames")


@dataclass(frozen=True)
class ProgrammingTarget:
    identifier: str
    bitstream: Path
    toolchain_roots: tuple[Path, ...]


@dataclass(frozen=True)
class XprProgram:
    identifier: str
    fpga: Fpga
    top: str
    constraints: Path
    xpr: Path


@dataclass(frozen=True)
class CleanupTarget:
    identifier: str
    outputs: tuple[Path, ...]
    auxiliary: Path


@dataclass(frozen=True)
class Project:
    root: Path
    identifier: str
    simulations: tuple[Simulation, ...]
    programs: tuple[SynthesisProgram | ProgrammingTarget | XprProgram, ...]
    exports: dict[str, str]
    imports: dict[str, tuple[str, ...]]
    command: str = "script"
    simulation_ids: tuple[str, ...] = ()
    program_ids: tuple[str, ...] = ()
    cleanup_targets: tuple[CleanupTarget, ...] = ()

    @property
    def aux_dir(self) -> Path:
        return self.root / "build" / "aux"

    @property
    def script(self) -> Path:
        return self.root / "jobs.sh"

    def filelist(self, simulation: Simulation) -> Path:
        return self.aux_dir / f"{simulation.identifier}.f"

    def job_dir(self, item: Simulation | SynthesisProgram | ProgrammingTarget | CleanupTarget) -> Path:
        return self.root / "build" / "jobs" / item.identifier

    def yosys_script(self, program: SynthesisProgram) -> Path:
        return self.aux_dir / f"{program.identifier}.ys"
