"""Build source symbol tables and file dependency models."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from models import Project, Simulation, SourceModel, SourceSymbols, SynthesisProgram
from hdl import ParsedSource, parse_source
from util import ConfigError, project_path


FULL_COMMANDS = {"model", "auxiliary", "script"}
HASH_JSON_RE = re.compile(r"[0-9a-f]{64}\.json\Z")


def source_index(project: Project) -> tuple[dict[str, str], dict[str, ParsedSource]]:
    sources: set[Path] = set()
    config_path = project.root / "configuration.toml"
    for directory in dict.fromkeys((*project.source_directories, *project.simulation_directories)):
        if not directory.is_dir():
            raise ConfigError(f"{config_path}: source directory does not exist: {directory}")
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in {".v", ".sv"}:
                sources.add(project_path(project.root, str(path), str(config_path)))
    if not sources:
        raise ConfigError(f"{config_path}: no Verilog source files in configured source directories")

    exports: dict[str, str] = {}
    parsed: dict[str, ParsedSource] = {}
    for source in sorted(sources):
        path = source.relative_to(project.root).as_posix()
        parsed[path] = parse_source(project.root, source, project.hdl)
        for symbol in parsed[path].symbols.exports:
            if symbol in exports:
                raise ConfigError(
                    f"{parsed[path].locations[symbol]}: duplicate export {symbol!r}; "
                    f"already exported by {exports[symbol]}"
                )
            exports[symbol] = path
    interfaces = {name for item in parsed.values() for name in item.interfaces}
    for path, item in parsed.items():
        imported = set(item.symbols.imports) | (set(item.named_types) & interfaces)
        parsed[path] = replace(item, symbols=SourceSymbols(tuple(sorted(imported)), item.symbols.exports))
    return exports, parsed


def build_model(project: Project) -> Project:
    """Parse sources globally, then resolve only the required file graph."""
    exports, parsed = source_index(project)
    roots: set[str] = set()
    targets = [
        ("simulation" if isinstance(target, Simulation) else "project", target.identifier, target.top)
        for target in (*project.simulations, *project.programs)
        if isinstance(target, (Simulation, SynthesisProgram))
    ]
    for target in project.xprs:
        targets.append(("project", target.identifier, target.top))
    targets.extend(("simulation", simulation.identifier, simulation.top) for simulation in project.xpr_simulations)
    for kind, identifier, top in targets:
        if top not in exports:
            raise ConfigError(
                f"{project.root / 'configuration.toml'}: {kind} {identifier!r} has no exported top-symbol {top!r}"
            )
        roots.add(exports[top])
    if project.command in FULL_COMMANDS:
        roots.update(parsed)

    sources: dict[str, SourceModel] = {}
    visiting: set[str] = set()

    def visit(path: str) -> SourceModel:
        if path in sources:
            return sources[path]
        source_path = project.root / path
        if path in visiting:
            raise ConfigError(f"{source_path}: cyclic source dependency")
        visiting.add(path)
        dependencies: set[str] = set()
        for symbol in parsed[path].symbols.imports:
            if symbol not in exports:
                location = parsed[path].locations.get(symbol, str(source_path))
                raise ConfigError(f"{location}: unresolved import {symbol!r}")
            if exports[symbol] != path:
                dependencies.add(exports[symbol])
        closure: dict[str, None] = {}
        for dependency in sorted(dependencies):
            closure.update(dict.fromkeys(visit(dependency).closure))
            closure[dependency] = None
        visiting.remove(path)
        source = SourceModel(parsed[path].symbols, tuple(sorted(dependencies)), tuple(closure), parsed[path].includes)
        sources[path] = source
        return source

    for path in sorted(roots):
        visit(path)
    for target in project.xprs:
        path = exports[target.top]
        for source in (*sources[path].closure, path):
            if project.is_simulation_source(source):
                raise ConfigError(
                    f"{project.root / source}: "
                    f"project {target.identifier!r} depends on a file in directories.simulation"
                )
    return replace(project, exports=exports, sources=sources)


def source_filename(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest() + ".json"


def generate_model(project: Project) -> None:
    """Persist the validated model; selected commands preserve unrelated files."""
    for directory in (project.symbol_dir, project.model_dir):
        directory.mkdir(parents=True, exist_ok=True)
    expected: set[str] = set()
    for path, source in sorted(project.sources.items()):
        filename = source_filename(path)
        expected.add(filename)
        records = (
            (project.symbol_dir, {"path": path, "import": source.symbols.imports, "export": source.symbols.exports}),
            (project.model_dir, {"path": path, "dependencies": source.dependencies,
                                 "closure": source.closure, "includes": source.includes}),
        )
        for directory, record in records:
            content = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
            output = directory / filename
            if not output.exists() or output.read_text(encoding="utf-8") != content:
                output.write_text(content, encoding="utf-8")
    if project.command in FULL_COMMANDS:
        for directory in (project.symbol_dir, project.model_dir):
            for output in directory.iterdir():
                if output.is_file() and HASH_JSON_RE.fullmatch(output.name) and output.name not in expected:
                    output.unlink()
