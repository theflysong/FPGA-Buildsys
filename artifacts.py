"""Shared artifact summaries for the Python CLI and generated shell jobs."""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex

from models import ImplementationProgram, Program, ProgrammingTarget, Project, Simulation, SynthesisProgram
from util import BUILDSYS_DIR, render_template


def label(kind: str, identifier: str) -> str:
    return f"constraints ({identifier}, input)" if kind == "constraints" else f"{kind} ({identifier})"


def target_artifacts(target, *, waveforms: bool = True, stage: str = "bitstream") -> list[tuple[str, Path]]:
    if isinstance(target, Simulation):
        pairs = [("vvp", target.vvp)] + ([("vcd", target.vcd)] if waveforms else [])
    elif isinstance(target, ProgrammingTarget):
        pairs = [("bitstream", target.bitstream)]
    else:
        pairs = [("synthesis", target.synthesis)] if isinstance(target, SynthesisProgram) else []
        if isinstance(target, ImplementationProgram) and stage != "synthesis":
            pairs.extend((("implementation", target.implementation), ("constraints", target.constraints)))
        if isinstance(target, Program) and stage == "bitstream":
            pairs.extend((("frames", target.frames), ("bitstream", target.bitstream)))
    return [(label(kind, target.identifier), path) for kind, path in pairs]


def report(entries: list[tuple[str, Path]]) -> None:
    existing = list(dict.fromkeys((kind, path.resolve()) for kind, path in entries if path.exists()))
    if existing:
        print("=" * 60, flush=True)
        for kind, path in existing:
            print(f"The path of {kind}: {path}", flush=True)
        print("=" * 60, flush=True)


def shell_report(project: Project, entries: list[tuple[str, Path]]) -> str:
    return render_template("shell/report.sh", reporter=shlex.quote(str(BUILDSYS_DIR / "artifacts.py")),
                           artifacts=" ".join(shlex.quote(value) for kind, path in entries
                                              for value in (kind, str(path)))).rstrip("\n")


def report_project(project: Project, target_id: str | None) -> None:
    command = project.command
    entries: list[tuple[str, Path]] = []
    if command == "model":
        entries = [("symbol directory", project.symbol_dir), ("model directory", project.model_dir)]
    elif command == "auxiliary":
        entries = [("auxiliary directory", project.auxiliary_dir)]
    elif command == "script":
        entries = [("task dispatcher", project.script), ("task directory", project.root / "build/jobs")]
    elif command == "xpr":
        if project.xpr is not None:
            entries.append(("xpr", project.xpr))
        entries.extend((label("constraints", item.identifier), item.constraints) for item in project.xprs)
    elif command.startswith("xpr-"):
        entries = [(label(kind, item.identifier), path) for item in project.xpr_stages for kind, path in item.artifacts]
    elif command in {"build", "simulate"}:
        entries = [entry for item in project.simulations if item.identifier == target_id
                   for entry in target_artifacts(item, waveforms=command == "simulate")]
    elif command.startswith("yosys-"):
        entries = [entry for item in project.programs if item.identifier == target_id for entry in target_artifacts(item)]
    report(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*")
    args = parser.parse_args()
    if len(args.artifacts) % 2:
        parser.error("expected label/path pairs")
    report([(kind, Path(path)) for kind, path in zip(args.artifacts[::2], args.artifacts[1::2])])


if __name__ == "__main__":
    main()
