"""Vivado export configuration and pytcl transport with a simulated Vivado."""

from __future__ import annotations

from contextlib import nullcontext, redirect_stderr, redirect_stdout
from dataclasses import replace
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from completion_ids import candidate_ids
from models import SourceModel, SourceSymbols, XprProject
from task.configure import configure as configure_project
from task.model import build_model
from toolchains import select_toolchain
from util import ConfigError


ENTRY = Path(__file__).resolve().parents[1] / "main.py"
HAS_PYTCL = importlib.util.find_spec("pytcl") is not None
HAS_TCL = importlib.util.find_spec("tkinter") is not None


def configure(root: Path, command: str = "script", target_id: str | None = None):
    """Exercise configuration and its model prerequisite without generating files."""
    project = configure_project(root, command, target_id)
    return build_model(project) if project.source_directories else project

# Use real pytcl.Vivado and TCLCall serialization, backed by a Tcl interpreter
# implementing only Vivado's project commands. No FPGA tools or licenses are used.
FAKE_VIVADO = r'''#!/usr/bin/env python3
import json, os, sys, tkinter
from multiprocessing.connection import Listener
from pathlib import Path

tcl = tkinter.Tcl()
current = ""
project_file = None
sources = {}
source_sets = {"sources_1": "", "constrs_1": "", "sim_1": "sources_1"}
current_sim = "sim_1"
simulation_enabled = {}

def record(name, *args):
    global current, project_file, current_sim
    with open(os.environ["XPR_CALLS"], "a") as stream:
        stream.write(json.dumps([name, *args]) + "\n")
    if name == os.environ.get("XPR_FAIL"):
        return tcl.call("error", "simulated Vivado failure")
    if name == "create_project":
        current = args[1]
        directory = Path(args[2])
        directory.mkdir(parents=True, exist_ok=True)
        project_file = directory / (current + ".xpr")
    elif name == "add_files":
        sources.setdefault(args[2], []).append(args[3])
    elif name == "get_runs":
        return args[0]
    elif name == "get_property":
        return "synthesis-flow" if args[1] == "synth_1" else "implementation-flow"
    elif name == "get_filesets":
        return args[0]
    elif name == "get_files":
        if args[-1] in source_sets:
            return tuple(sources.get(args[-1], []))
        return tuple(path for path in sources.get(args[1], []) if path == args[-1])
    elif name == "create_fileset":
        source_sets[args[1]] = "sources_1"
    elif name == "current_fileset":
        current_sim = args[-1] if len(args) > 1 else current_sim
    elif name == "delete_fileset":
        if args[0] == current_sim:
            return tcl.call("error", "cannot delete an active fileset")
        del source_sets[args[0]]
    elif name == "set_property" and args[0] == "SOURCE_SET":
        source_sets[args[2]] = args[1]
    elif name == "set_property" and args[0] == "USED_IN_SIMULATION":
        for path in tcl.splitlist(args[2]):
            simulation_enabled[path] = args[1] == "true"
    elif name == "set_property" and args[0] == "file_type" and not args[2]:
        return tcl.call("error", "set_property requires file objects")
    elif name == "current_project":
        return current
    elif name == "close_project":
        project_file.write_text(json.dumps({
            **{fileset: sources.get(fileset, []) for fileset in source_sets},
            "compile": {fileset: [path for path in sources.get(parent, [])
                                  if simulation_enabled.get(path, True)] + sources.get(fileset, [])
                        for fileset, parent in source_sets.items() if fileset.startswith("sim_")}
        }))
    return ""

for name in ("create_project", "add_files", "get_filesets", "get_files", "set_property",
             "current_project", "create_fileset", "current_fileset", "delete_fileset",
             "update_compile_order", "close_project", "get_runs", "get_property", "create_run", "delete_runs", "current_run"):
    tcl.createcommand(name, lambda *args, name=name: record(name, *args))

address = sys.argv[sys.argv.index("-tclargs") + 1]
with Listener(address) as listener:
    with listener.accept() as connection:
        while True:
            try:
                expression = connection.recv()
            except EOFError:
                break
            try:
                result = tcl.eval(expression)
                status = 0
            except tkinter.TclError as exc:
                result, status = str(exc), 1
            connection.send(json.dumps({"result": result, "status": status}))
'''


class XprTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="xpr {$[literal]}; ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        select_toolchain(self.root, "vivado")
        (self.root / "src").mkdir()
        (self.root / "sim").mkdir()
        (self.root / "constraints").mkdir()
        self.leaf = self.root / "src/leaf {$[literal]}.sv"
        self.leaf.write_text("module leaf; endmodule\n")
        (self.root / "src/top.v").write_text("module top; leaf dut(); endmodule\n")
        (self.root / "src/helper.sv").write_text("module helper; endmodule\n")
        (self.root / "sim/first.v").write_text("module tb_first; top dut(); helper utils(); endmodule\n")
        (self.root / "sim/second.v").write_text("module tb_second; leaf dut(); endmodule\n")
        (self.root / "constraints/board.xdc").write_text("# XDC\n")
        self.config = self.root / "configuration.toml"
        self.original = (
            'id = "example"\nname = "Vivado export"\n'
            '[directories]\nsources = ["src"]\nsimulation = ["sim"]\nconstraints = ["constraints"]\n'
            '[[fpga]]\nid = "board"\npart = "xc7a35tcsg324-1"\n'
            '[[project]]\nid = "core"\nfpga = "board"\ntop-symbol = "top"\nconstraints = "board.xdc"\n'
            '[[simulation]]\nid = "first"\ntop-symbol = "tb_first"\n'
            '[[simulation]]\nid = "second"\ntop-symbol = "tb_second"\ntimescale = "10ns/1ps"\n'
        )
        self.config.write_text(self.original)
        # Keep the launcher's PATH entry free of the project path's semicolon.
        temporary_tools = tempfile.TemporaryDirectory(prefix="xpr tools ")
        self.addCleanup(temporary_tools.cleanup)
        self.tools = Path(temporary_tools.name)
        self.vivado = self.tools / ("vivado.bat" if os.name == "nt" else "vivado")
        if os.name == "nt":
            (self.tools / "fake_vivado.py").write_text(FAKE_VIVADO)
            self.vivado.write_text(f'@"{sys.executable}" "%~dp0fake_vivado.py" %*\n')
        else:
            self.vivado.write_text(FAKE_VIVADO)
        self.vivado.chmod(0o755)
        self.calls = self.root / "calls.jsonl"
        self.env = dict(os.environ, PATH=f"{self.tools}{os.pathsep}{os.environ['PATH']}",
                        XPR_CALLS=str(self.calls))

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(ENTRY), "--project", str(self.root), *args],
                              env=self.env, cwd=self.root.parent, capture_output=True, text=True, timeout=20)

    def fake_export(self, project=None):
        import tkinter
        namespace = {}
        with patch.dict(os.environ, XPR_CALLS=str(self.calls)):
            exec(FAKE_VIVADO[:FAKE_VIVADO.index("address = sys.argv")], namespace)
        tcl = namespace["tcl"]

        class Vivado:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def __getattr__(self, name):
                return lambda *args: tcl.eval(name + " " + " ".join(map(str, args)))

        output, errors = io.StringIO(), io.StringIO()
        model = patch("planner.build_model", return_value=project) if project is not None else nullcontext()
        with patch.dict(sys.modules, pytcl=SimpleNamespace(Vivado=Vivado, TCLError=tkinter.TclError)), \
                patch.dict(os.environ, XPR_CALLS=str(self.calls)), \
                patch("task.vivado.xpr.shutil.which", return_value="vivado"), \
                model, \
                redirect_stdout(output), redirect_stderr(errors):
            result = main.main(["--project", str(self.root), "xpr"])
        return SimpleNamespace(returncode=result, stdout=output.getvalue(), stderr=errors.getvalue())

    def test_export_configures_all_targets_without_local_fpga_settings(self):
        project = configure(self.root, "xpr")
        self.assertEqual(project.xpr, self.root / "build/vivado/example/example.xpr")
        self.assertEqual([item.identifier for item in project.xprs], ["core"])
        self.assertEqual([item.identifier for item in project.xpr_simulations], ["first", "second"])
        self.assertEqual(project.xpr_simulations[0].timescale, "1ns/1ps")
        self.assertFalse((self.root / "build").exists())
        self.config.write_text(self.original + '[[project]]\nid="unfinished"\n')
        with self.assertRaisesRegex(ConfigError, "top-symbol"):
            configure(self.root, "xpr")

    def test_invalid_inputs_and_legacy_fields(self):
        for text, message in (
            (self.original + '[[xpr]]\nid="old"\n', "obsolete"),
            (self.original.replace('[directories]', '[directories]\nvvp="old"'), "obsolete"),
            (self.original.replace('id = "first"', 'id = "first"\nvcd="old"'), "obsolete"),
            (self.original.replace('id = "first"', 'id = "core"'), "duplicate task id"),
            (self.original.replace('id = "first"', 'id = "../bad"'), "invalid id"),
            (self.original.replace('top-symbol = "tb_first"', 'top-symbol = "missing"'), "no exported top-symbol"),
            (self.original.replace('fpga = "board"', 'fpga = "missing"'), "unknown fpga"),
            (self.original.replace('constraints = "board.xdc"', 'constraints = "missing.xdc"'), "does not exist"),
            (self.original.replace('timescale = "10ns/1ps"', 'timescale = "invalid"'), "invalid timescale"),
        ):
            with self.subTest(message=message):
                self.config.write_text(text)
                with self.assertRaisesRegex(ConfigError, message):
                    configure(self.root, "xpr")
                self.assertFalse((self.root / "build").exists())
        self.config.write_text(self.original)
        with self.assertRaisesRegex(ConfigError, "no longer takes"):
            configure(self.root, "xpr", "old")

    def test_constraints_unique_match_and_ambiguity(self):
        (self.root / "other").mkdir()
        self.config.write_text(self.original.replace('["constraints"]', '["other", "constraints"]'))
        self.assertEqual(configure(self.root, "xpr").xprs[0].constraints,
                         self.root / "constraints/board.xdc")
        (self.root / "other/board.xdc").write_text("# duplicate")
        with self.assertRaisesRegex(ConfigError, "ambiguous constraints"):
            configure(self.root, "xpr")

    def test_all_target_dependencies_and_directory_roles(self):
        (self.root / "sim/second.v").write_text('module tb_second; missing dut(); endmodule')
        with self.assertRaisesRegex(ConfigError, "unresolved import"):
            configure(self.root, "xpr")
        (self.root / "sim/second.v").write_text('module tb_second; endmodule')
        (self.root / "src/top.v").write_text('module top; tb_second dut(); endmodule')
        with self.assertRaisesRegex(ConfigError, "directories.simulation"):
            configure(self.root, "xpr")

    @unittest.skipUnless(HAS_TCL, "Requires Tcl")
    def test_headers_include_directories_and_macros_reach_filesets(self):
        headers = self.root / "headers } 中文"
        headers.mkdir()
        (headers / "leaf.svh").write_text('`define LEAF leaf\n')
        (headers / "outer.vh").write_text('`include "leaf.svh"\n')
        (self.root / "src/top.v").write_text('`include "outer.vh"\n'
            'module top; `ifdef FEATURE\n`LEAF dut();\n`endif\nendmodule')
        self.config.write_text(self.original + '[hdl]\ninclude-dirs=["headers } 中文"]\n'
                               'defines={FEATURE="1",TEXT=\'"a b $[]"\'}\n', encoding="utf-8")
        # Exercise the backend's model-to-Tcl boundary independently of parsing.
        project = configure_project(self.root, "xpr")
        leaf = self.leaf.relative_to(self.root).as_posix()
        sources = {
            leaf: SourceModel(SourceSymbols((), ("leaf",)), (), ()),
            "src/helper.sv": SourceModel(SourceSymbols((), ("helper",)), (), ()),
            "src/top.v": SourceModel(SourceSymbols(("leaf",), ("top",)), (leaf,), (leaf,),
                                      ("headers } 中文/leaf.svh", "headers } 中文/outer.vh")),
            "sim/first.v": SourceModel(SourceSymbols(("top", "helper"), ("tb_first",)),
                                       ("src/top.v", "src/helper.sv"), (leaf, "src/helper.sv", "src/top.v")),
            "sim/second.v": SourceModel(SourceSymbols(("leaf",), ("tb_second",)), (leaf,), (leaf,)),
        }
        exports = {name: path for path, item in sources.items() for name in item.symbols.exports}
        result = self.fake_export(replace(project, sources=sources, exports=exports))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        import tkinter
        tcl = tkinter.Tcl()
        include_dirs = next(row[2] for row in calls if row[:2] == ["set_property", "include_dirs"])
        self.assertEqual(tcl.splitlist(include_dirs), (headers.as_posix(),))
        defines = next(row[2] for row in calls if row[:2] == ["set_property", "verilog_define"])
        self.assertEqual(tcl.splitlist(defines), ("FEATURE=1", 'TEXT="a b $[]"'))
        for file_type, header in (("Verilog Header", "outer.vh"), ("SystemVerilog Header", "leaf.svh")):
            self.assertIn(["set_property", "file_type", file_type, str(headers / header)], calls)

    @unittest.skipUnless(HAS_TCL, "Requires Tcl")
    def test_single_export_multiple_parts_and_independent_simulation_closures(self):
        self.config.write_text(self.original + '[[fpga]]\nid="large"\npart="xc7a100tcsg324-1"\n'
                               '[[project]]\nid="other"\nfpga="large"\ntop-symbol="leaf"\nconstraints="board.xdc"\n')
        for _ in range(2):
            result = self.fake_export()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("The path of xpr:"), 1)
        path = self.root / "build/vivado/example/example.xpr"
        filesets = json.loads(path.read_text())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len([row for row in calls if row[0] == "create_project"]), 2)
        self.assertIn(["create_project", "-force", "example", str(path.parent), "-part", "xc7a35tcsg324-1"], calls)
        self.assertEqual(filesets["src_core"], [str(self.leaf), str(self.root / "src/top.v")])
        self.assertEqual(filesets["src_other"], [str(self.leaf)])
        self.assertEqual(set(filesets["sim_first"]), {str(self.leaf), str(self.root / "src/top.v"),
                                                    str(self.root / "src/helper.sv"), str(self.root / "sim/first.v")})
        self.assertEqual(filesets["sim_second"], [str(self.leaf), str(self.root / "sim/second.v")])
        for identifier, part in (("core", "xc7a35tcsg324-1"), ("other", "xc7a100tcsg324-1")):
            self.assertIn(["create_run", "synth_" + identifier, "-flow", "synthesis-flow", "-srcset", "src_" + identifier,
                           "-constrset", "constrs_" + identifier, "-part", part], calls)
            self.assertIn(["create_run", "impl_" + identifier, "-flow", "implementation-flow", "-parent_run", "synth_" + identifier,
                           "-constrset", "constrs_" + identifier, "-part", part], calls)
        self.assertIn(["current_run", "-synthesis", "synth_core"], calls)
        self.assertIn(["current_fileset", "-simset", "sim_first"], calls)
        self.assertFalse((self.root / ".buildsys/fpga").exists())
        self.assertFalse((self.root / "jobs.sh").exists())

    @unittest.skipUnless(HAS_TCL, "Requires Tcl")
    def test_design_only_and_simulation_only_export(self):
        for only in ("design", "simulation"):
            with self.subTest(only=only):
                text = self.original
                if only == "design":
                    text = text[:text.index("[[simulation]]")]
                else:
                    a=text.index("[[fpga]]");b=text.index("[[simulation]]")
                    text=text[:a]+text[b:]
                self.config.write_text(text)
                self.calls.unlink(missing_ok=True)
                result = self.fake_export()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
                create = next(row for row in calls if row[0] == "create_project")
                self.assertEqual("-part" in create, only == "design")
                if only == "simulation":
                    self.assertFalse(any(row[0] == "create_run" for row in calls))

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Requires pytcl and Tcl")
    def test_cli_transport_uses_real_pytcl_with_fake_vivado(self):
        result = self.cli("xpr")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "build/vivado/example/example.xpr").is_file())

    def test_missing_dependency_and_tool_errors(self):
        error = io.StringIO()
        with patch.dict(sys.modules, {"pytcl": None}), redirect_stderr(error):
            result = main.main(["--project", str(self.root), "xpr"])
        self.assertEqual(result, 1)
        self.assertIn("pytcl-eda", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())


if __name__ == "__main__":
    unittest.main()
