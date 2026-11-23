"""Collect Verilog/SystemVerilog source files without parsing HDL."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import re

from models import Project
from util import ConfigError, project_path


HASH_JSON_RE = re.compile(r"[0-9a-f]{64}\.json\Z")


def build_model(project: Project) -> Project:
    """Recursively collect all configured compilation units in stable path order."""
    sources: set[str] = set()
    config_path = project.root / "configuration.toml"
    for directory in dict.fromkeys((*project.source_directories, *project.simulation_directories)):
        if not directory.is_dir():
            raise ConfigError(f"{config_path}: source directory does not exist: {directory}")
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".v", ".sv"}:
                source = project_path(project.root, str(path), str(config_path))
                sources.add(source.relative_to(project.root).as_posix())
    if not sources:
        raise ConfigError(f"{config_path}: no Verilog source files in configured source directories")
    return replace(project, sources=tuple(sorted(sources)))


def source_filename(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest() + ".json"


def generate_model(project: Project) -> None:
    """Persist only source paths, preserving timestamps when the list is unchanged."""
    project.model_dir.mkdir(parents=True, exist_ok=True)
    expected: set[str] = set()
    for path in project.sources:
        filename = source_filename(path)
        expected.add(filename)
        content = json.dumps({"path": path}, ensure_ascii=False, indent=2) + "\n"
        output = project.model_dir / filename
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            output.write_text(content, encoding="utf-8")
    for output in project.model_dir.iterdir():
        if output.is_file() and HASH_JSON_RE.fullmatch(output.name) and output.name not in expected:
            output.unlink()
