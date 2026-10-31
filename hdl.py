"""Preprocess and inspect HDL syntax without elaborating or requiring FPGA tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from models import HdlOptions, SourceSymbols
from util import ConfigError, project_path


@dataclass(frozen=True)
class ParsedSource:
    symbols: SourceSymbols
    includes: tuple[str, ...]
    locations: dict[str, str]
    # Named types can be interface ports or ordinary local typedefs. Resolve
    # these only after the entire project's interface index is available.
    named_types: tuple[str, ...]
    interfaces: tuple[str, ...]


def parse_source(root: Path, source: Path, options: HdlOptions) -> ParsedSource:
    try:
        import pyslang as slang
    except ImportError as exc:
        raise ConfigError(
            "Source analysis requires pyslang; run buildsys init-venv "
            "or install FPGA-Buildsys/requirements.txt in the active Python environment"
        ) from exc

    manager = slang.SourceManager()
    preprocessor = slang.PreprocessorOptions()
    # PathLike bindings preserve Windows Unicode paths; the string-based
    # fromFile/addUserDirectories overloads do not in pyslang 8.0.0.
    preprocessor.additionalIncludePaths = list(options.include_dirs)
    # The simulation job supplies the real path at compile time. Its value
    # has no effect on dependency discovery, but must be valid HDL syntax.
    preprocessor.predefines = ['__VCD_FILE__="buildsys-analysis.vcd"',
                               *(f"{name}={value}" for name, value in options.defines)]
    bag = slang.Bag([preprocessor])
    tree = slang.SyntaxTree.fromBuffer(manager.readSource(source), manager, bag)

    def location(loc) -> str:
        loc = manager.getFullyOriginalLoc(loc)
        path = manager.getFullPath(loc.buffer) or source
        return f"{path}:{manager.getLineNumber(loc)}:{manager.getColumnNumber(loc)}"

    errors = [diagnostic for diagnostic in tree.diagnostics if diagnostic.isError()]
    if errors:
        engine = slang.DiagnosticEngine(manager)
        raise ConfigError("\n".join(f"{location(error.location)}: {engine.formatMessage(error)}"
                                    for error in errors))

    exports: list[str] = []
    imports: set[str] = set()
    interfaces: set[str] = set()
    named_types: set[str] = set()
    scoped: dict[str, str] = {}
    local_types: set[str] = set()
    locations: dict[str, str] = {}

    def reference(token, collection=imports) -> None:
        name = token.valueText
        if name:
            collection.add(name)
            locations.setdefault(name, location(token.location))

    def visit(node) -> None:
        kind = node.kind.name
        if kind in ("ModuleDeclaration", "InterfaceDeclaration", "PackageDeclaration", "ProgramDeclaration"):
            token = getattr(node, "header", node).name
            if token.valueText in exports:
                raise ConfigError(f"{location(token.location)}: duplicate export {token.valueText!r}")
            exports.append(token.valueText)
            locations.setdefault(token.valueText, location(token.location))
            if kind == "InterfaceDeclaration":
                interfaces.add(token.valueText)
        elif kind == "HierarchyInstantiation":
            reference(node.type)
        elif kind == "PackageImportItem":
            reference(node.getFirstToken())
        elif kind == "InterfacePortHeader":
            token = node.getFirstToken()
            # The generic `interface port` form has no concrete dependency.
            if token.kind.name == "Identifier":
                reference(token)
        elif kind == "ScopedName":
            left = node.left
            if left.kind.name == "IdentifierName":
                token = left.identifier
                scoped.setdefault(token.valueText, location(token.location))
        elif kind == "NamedType":
            name = node.name
            if name.kind.name == "IdentifierName":
                reference(name.identifier, named_types)
        elif kind in ("ClassDeclaration", "TypedefDeclaration", "ForwardTypedefDeclaration"):
            local_types.add(node.name.valueText)

    tree.root.visit(visit)
    # A class / typedef scope is local syntax, not a package dependency.
    for name, loc in scoped.items():
        if name not in local_types and name != "std":
            imports.add(name)
            locations.setdefault(name, loc)

    includes: set[str] = set()
    for buffer in manager.getAllBuffers():
        path = manager.getFullPath(buffer)
        if path and Path(path).is_file():
            included = project_path(root, str(path), str(source))
            if included != source:
                includes.add(included.relative_to(root).as_posix())
    return ParsedSource(SourceSymbols(tuple(sorted(imports)), tuple(sorted(exports))),
                        tuple(sorted(includes)), locations, tuple(sorted(named_types)),
                        tuple(sorted(interfaces)))
