"""Project configuration data shared by the planner and tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class XprSimulation:
    identifier: str
    top: str
    timescale: str

    @property
    def fileset(self) -> str:
        return f"sim_{self.identifier}"


@dataclass(frozen=True)
class XprProject:
    identifier: str
    project_id: str
    fpga: Fpga
    top: str
    constraints: Path
    simulations: tuple[XprSimulation, ...]
    xpr: Path


@dataclass(frozen=True)
class XprStageTarget:
    """Resolved information used by commands operating on an existing XPR."""

    xpr_id: str
    xpr: Path
    top: str
    simulations: tuple[XprSimulation, ...]
    synthesis_run: str = "synth_1"
    implementation_run: str = "impl_1"
    bitstream: Path | None = None


@dataclass(frozen=True)
class CleanupTarget:
    identifier: str
    outputs: tuple[Path, ...]
    auxiliary: Path


@dataclass(frozen=True)
class SourceSymbols:
    imports: tuple[str, ...]
    exports: tuple[str, ...]


@dataclass(frozen=True)
class SourceModel:
    symbols: SourceSymbols
    dependencies: tuple[str, ...]
    closure: tuple[str, ...]


@dataclass(frozen=True)
class Project:
    root: Path
    identifier: str
    simulations: tuple[Simulation, ...]
    programs: tuple[SynthesisProgram | ProgrammingTarget, ...]
    command: str = "script"
    simulation_ids: tuple[str, ...] = ()
    program_ids: tuple[str, ...] = ()
    cleanup_targets: tuple[CleanupTarget, ...] = ()
    xprs: tuple[XprProject, ...] = ()
    xpr_stages: tuple[XprStageTarget, ...] = ()
    source_directories: tuple[Path, ...] = ()
    simulation_directories: tuple[Path, ...] = ()
    fpgas: tuple[Fpga, ...] = ()
    exports: dict[str, str] = field(default_factory=dict)
    sources: dict[str, SourceModel] = field(default_factory=dict)
    toolchain: str | None = None

    def is_simulation_source(self, source: str) -> bool:
        return any((self.root / source).is_relative_to(directory) for directory in self.simulation_directories)

    @property
    def model_dir(self) -> Path:
        return self.root / "build" / "model"

    @property
    def symbol_dir(self) -> Path:
        return self.root / "build" / "symbol"

    @property
    def auxiliary_dir(self) -> Path:
        return self.root / "build" / "auxiliary"

    @property
    def script(self) -> Path:
        return self.root / "jobs.sh"

    def filelist(self, simulation: Simulation) -> Path:
        return self.auxiliary_dir / f"{simulation.identifier}.f"

    def job_dir(self, item: Simulation | SynthesisProgram | ProgrammingTarget | CleanupTarget) -> Path:
        return self.root / "build" / "jobs" / item.identifier

    def yosys_script(self, program: SynthesisProgram) -> Path:
        return self.auxiliary_dir / f"{program.identifier}.ys"
