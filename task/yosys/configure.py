"""Initialize and load local settings required by the Yosys backend."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys

from models import Fpga, Project, SynthesisProgram
from util import ConfigError, external_path, fpga_config_path, read_toml


FPGA_TEMPLATE = '''# 本地 FPGA 配置；相对路径以项目根目录为基准，也支持绝对路径。
# 必填: Project X-Ray 数据库目录。
xray-database = ""

# 可选: 按列表顺序查找各目录及其 bin/；空列表使用 PATH。
toolchain-root = []

# FPGA 构建必填: Python 模块搜索目录列表，例如 Project X-Ray 源码目录。
PYTHONPATH = []
'''


def initialize_fpga_config(root: Path, fpga: Fpga) -> bool:
    path = fpga_config_path(root, fpga.identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(FPGA_TEMPLATE)
    return True


def toolchain_roots(root: Path, data: dict, path: Path) -> tuple[Path, ...]:
    roots = data.get("toolchain-root", [])
    if not isinstance(roots, list) or not all(isinstance(value, str) and value.strip() for value in roots):
        raise ConfigError(
            f'{path}: toolchain-root must be a list of nonempty strings; '
            'use ["path"] for one directory or [] to use PATH'
        )
    return tuple(external_path(root, value) for value in roots)


def load_fpga_config(root: Path, fpga: Fpga) -> Fpga:
    path = fpga_config_path(root, fpga.identifier)
    data = read_toml(path)
    database = data.get("xray-database", "")
    if not isinstance(database, str):
        raise ConfigError(f"{path}: xray-database must be a string; leave it empty if not configured")
    roots = toolchain_roots(root, data, path)
    python_paths = data.get("PYTHONPATH", [])
    if not isinstance(python_paths, list) or not all(
        isinstance(value, str) and value.strip() for value in python_paths
    ):
        raise ConfigError(f'{path}: PYTHONPATH must be a list of nonempty strings; use ["path"]')
    return replace(
        fpga,
        xray_database=external_path(root, database) if database.strip() else None,
        toolchain_roots=roots,
        python_paths=tuple(external_path(root, value) for value in python_paths),
    )


def configure_fpgas(project: Project) -> Project:
    """Initialize user-owned settings after public configuration and model checks."""
    fpgas: dict[str, Fpga] = {}
    for fpga in project.fpgas:
        if initialize_fpga_config(project.root, fpga):
            path = fpga_config_path(project.root, fpga.identifier)
            print(f"Created {path}; fill xray-database and PYTHONPATH before FPGA builds. "
                  "toolchain-root is optional; use [] to use PATH.", file=sys.stderr)
        fpgas[fpga.identifier] = load_fpga_config(project.root, fpga)
    return replace(project, programs=tuple(
        replace(target, fpga=fpgas[target.fpga.identifier]) if isinstance(target, SynthesisProgram) else target
        for target in project.programs
    ))
