#!/usr/bin/env python3
"""Read task ids for completion without running project configuration."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tomllib


ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")


def candidate_ids(path: Path, kind: str) -> list[str]:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    entries = data.get(kind, [])
    if not isinstance(entries, list):
        return []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id")
        if isinstance(identifier, str) and ID_RE.fullmatch(identifier) and identifier not in result:
            result.append(identifier)
    return result


def xpr_simulation_ids(path: Path, xpr_id: str) -> list[str]:
    """Return simulations explicitly selected by one XPR table."""
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    xprs = data.get("xpr", [])
    if not isinstance(xprs, list):
        return []
    selected = None
    for entry in xprs:
        if isinstance(entry, dict) and entry.get("id") == xpr_id:
            selected = entry.get("simulations", [])
            break
    if not isinstance(selected, list):
        return []
    result: list[str] = []
    for identifier in selected:
        if isinstance(identifier, str) and ID_RE.fullmatch(identifier) and identifier not in result:
            result.append(identifier)
    return result


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "xpr-simulation":
        for identifier in xpr_simulation_ids(Path(argv[0]), argv[2]):
            print(identifier)
    elif len(argv) == 2 and argv[1] in {"simulation", "project", "xpr"}:
        for identifier in candidate_ids(Path(argv[0]), argv[1]):
            print(identifier)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
