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
class Program:
    identifier: str
    fpga: Fpga
    top: str
    synthesis: Path
    implementation: Path
    bitstream: Path
    constraints: Path

    @property
    def frames(self) -> Path:
        return self.bitstream.with_suffix(".frames")


@dataclass(frozen=True)
class Project:
    root: Path
    identifier: str
    simulations: tuple[Simulation, ...]
    programs: tuple[Program, ...]
    exports: dict[str, str]
    imports: dict[str, tuple[str, ...]]

    @property
    def aux_dir(self) -> Path:
        return self.root / "build" / "aux"

    @property
    def script(self) -> Path:
        return self.root / "jobs.sh"

    def filelist(self, simulation: Simulation) -> Path:
        return self.aux_dir / f"{simulation.identifier}.f"

    def job_dir(self, item: Simulation | Program) -> Path:
        return self.root / "build" / "jobs" / item.identifier

    def yosys_script(self, program: Program) -> Path:
        return self.aux_dir / f"{program.identifier}.ys"
