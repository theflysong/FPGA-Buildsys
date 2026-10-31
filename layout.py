"""The single source of truth for buildsys-owned product locations."""

from dataclasses import dataclass
from pathlib import Path

from util import ConfigError


@dataclass(frozen=True)
class Layout:
    root: Path

    def path(self, *parts: str) -> Path:
        root = self.root.resolve()
        path = (root / "build" / Path(*parts)).resolve()
        if not path.is_relative_to(root / "build"):
            raise ConfigError(f"Generated path must stay inside the project's build directory: {path}")
        return path

    def simulation(self, identifier: str, extension: str) -> Path:
        return self.path("icarus", identifier, f"{identifier}.{extension}")

    def design(self, identifier: str, extension: str) -> Path:
        return self.path("yosys", identifier, f"{identifier}.{extension}")

    def xpr(self, identifier: str) -> Path:
        return self.path("vivado", identifier, f"{identifier}.xpr")
