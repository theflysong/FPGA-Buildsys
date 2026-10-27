"""Vivado export configuration and pytcl transport with a simulated Vivado."""

from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import main
from completion_ids import candidate_ids
from models import XprProject
from task.configure import configure as configure_project
from task.model import build_model
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
    elif name == "get_filesets":
        return args[0]
    elif name == "get_files":
        if args[-1] in source_sets:
            return tuple(sources.get(args[-1], []))
        return tuple(path for path in sources.get(args[1], []) if path == args[-1])
    elif name == "create_fileset":
        source_sets[args[1]] = "sources_1"
    elif name == "current_fileset":
        current_sim = args[1]
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
             "update_compile_order", "close_project"):
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
        (self.root / "src").mkdir()
        (self.root / "sim").mkdir()
        (self.root / "constraints").mkdir()
        self.leaf = self.root / "src/leaf {$[literal]}.sv"
        self.leaf.write_text("module leaf; endmodule\n")
        self.leaf.with_suffix(".toml").write_text('[[module.export]]\nname = "leaf"\n')
        (self.root / "src/top.v").write_text("module top; leaf dut(); endmodule\n")
        (self.root / "src/top.toml").write_text(
            '[[module.export]]\nname = "top"\n[[module.import]]\nname = "leaf"\n'
        )
        (self.root / "src/helper.sv").write_text("module helper; endmodule\n")
        (self.root / "src/helper.toml").write_text('[[module.export]]\nname = "helper"\n')
        (self.root / "sim/first.v").write_text("module tb_first; top dut(); helper utils(); endmodule\n")
        (self.root / "sim/first.toml").write_text(
            '[[module.export]]\nname = "tb_first"\n'
            '[[module.import]]\nname = "top"\n[[module.import]]\nname = "helper"\n'
        )
        (self.root / "sim/second.v").write_text("module tb_second; leaf dut(); endmodule\n")
        (self.root / "sim/second.toml").write_text(
            '[[module.export]]\nname = "tb_second"\n[[module.import]]\nname = "leaf"\n'
        )
        (self.root / "constraints/board.xdc").write_text("# XDC\n")
        self.config = self.root / "configuration.toml"
        self.original = (
            'id = "example"\nname = "Vivado export"\n'
            '[directories]\nsources = ["src"]\nsimulation = ["sim"]\nconstraints = ["constraints"]\nxpr = "build/xpr"\n'
            '[[fpga]]\nid = "board"\npart = "xc7a35tcsg324-1"\n'
            '[[project]]\nid = "core"\nfpga = "board"\ntop-symbol = "top"\nconstraints = "board.xdc"\n'
            '[[simulation]]\nid = "first"\ntop-symbol = "tb_first"\ntimescale = "1ns/1ps"\n'
            '[[simulation]]\nid = "second"\ntop-symbol = "tb_second"\ntimescale = "10ns/1ps"\n'
            '[[xpr]]\nid = "export"\nproject = "core"\nsimulations = ["first", "second"]\n'
            '[[simulation]]\nid = "unfinished_simulation"\n'
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

    def test_configuration_is_scoped_and_does_not_create_fpga_settings(self) -> None:
        self.config.write_text(self.original +
                               '[[project]]\nid = "unfinished"\n[[xpr]]\nid = "unfinished_export"\nproject = "unfinished"\n')
        local = self.root / "build/fpga/board.toml"
        local.parent.mkdir(parents=True)
        local.write_text("invalid TOML [")
        project = configure(self.root, "xpr", "export")
        target, = project.xprs
        self.assertIsInstance(target, XprProject)
        self.assertEqual(target.project_id, "core")
        self.assertEqual(target.xpr, self.root / "build/xpr/export/export.xpr")
        self.assertEqual([simulation.identifier for simulation in target.simulations], ["first", "second"])
        self.assertEqual(project.programs, ())
        self.assertEqual(local.read_text(), "invalid TOML [")
        self.assertFalse((self.root / "build/xpr").exists())
        local.unlink()
        configure(self.root, "xpr", "export")
        self.assertFalse(local.exists())
        with self.assertRaisesRegex(ConfigError, "fpga must be a nonempty string"):
            configure(self.root, "xpr")

    def test_export_validates_directories_references_and_dependencies(self) -> None:
        cases = (
            (self.original.replace('xpr = "build/xpr"\n', ''), "directories.xpr"),
            (self.original.replace('xpr = "build/xpr"', 'xpr = ["build/xpr"]'), "directories.xpr"),
            (self.original.replace('xpr = "build/xpr"', 'xpr = "../outside"'), "path must stay inside"),
            (self.original.replace('fpga = "board"', 'fpga = "missing"'), "unknown fpga id"),
            (self.original.replace('top-symbol = "top"', 'top-symbol = "missing"'), "no exported top-symbol"),
            (self.original.replace('constraints = "board.xdc"', 'constraints = "missing.xdc"'), "constraints file does not exist"),
            (self.original.replace('project = "core"', 'project = "missing"'), "unknown project"),
            (self.original.replace('project = "core"', 'project = "first"'), "unknown project"),
            (self.original.replace('simulations = ["first", "second"]', 'simulations = ["missing"]'), "unknown simulation"),
            (self.original.replace('simulations = ["first", "second"]', 'simulations = ["core"]'), "unknown simulation"),
            (self.original.replace('simulations = ["first", "second"]', 'simulations = "first"'), "list of nonempty strings"),
            (self.original.replace('simulations = ["first", "second"]', 'simulations = ["first", "first"]'), "duplicate simulation reference"),
            (self.original.replace('top-symbol = "tb_first"', 'top-symbol = "missing"'), "no exported top-symbol"),
            (self.original.replace('timescale = "1ns/1ps"', 'timescale = "invalid"'), "invalid timescale"),
            (self.original + '[[xpr]]\nid = "export"\nproject = "core"\n', "duplicate xpr id"),
        )
        for text, message in cases:
            with self.subTest(message=message):
                self.config.write_text(text)
                with self.assertRaisesRegex(ConfigError, message):
                    configure(self.root, "xpr", "export")
                self.assertFalse((self.root / "build").exists())
        self.config.write_text(self.original)
        with self.assertRaisesRegex(ConfigError, "unknown xpr"):
            configure(self.root, "xpr", "unfinished_simulation")
        with self.assertRaisesRegex(ConfigError, "unknown xpr"):
            configure(self.root, "xpr", "core")
        (self.root / "src/top.toml").write_text(
            '[[module.export]]\nname = "top"\n[[module.import]]\nname = "missing"\n'
        )
        with self.assertRaisesRegex(ConfigError, "unresolved import"):
            configure(self.root, "xpr", "export")

    def test_explicit_xpr_tables_and_project_migration_are_required(self) -> None:
        self.config.write_text(self.original.replace('[[xpr]]', '[xpr]'))
        with self.assertRaisesRegex(ConfigError, "must be an array of tables"):
            configure(self.root, "xpr")
        self.config.write_text(self.original.replace(
            '[[xpr]]\nid = "export"\nproject = "core"\nsimulations = ["first", "second"]\n', ''
        ))
        with self.assertRaisesRegex(ConfigError, r"at least one \[\[xpr\]\]"):
            configure(self.root, "xpr")
        self.config.write_text(self.original.replace('[[project]]', '[[program]]'))
        with self.assertRaisesRegex(ConfigError, r"rename it to \[\[project\]\]"):
            configure(self.root, "xpr")
        self.assertFalse((self.root / "build").exists())

    def test_only_referenced_simulation_dependencies_are_required(self) -> None:
        metadata = self.root / "sim/first.toml"
        metadata.write_text('[[module.export]]\nname = "tb_first"\n[[module.import]]\nname = "missing"\n')
        with self.assertRaisesRegex(ConfigError, "unresolved import"):
            configure(self.root, "xpr", "export")
        self.config.write_text(self.original.replace('simulations = ["first", "second"]', 'simulations = []'))
        target, = configure(self.root, "xpr", "export").xprs
        self.assertEqual(target.simulations, ())
        self.config.write_text(self.original)
        metadata.write_text('[[module.export]]\nname = "tb_first"\n[[module.import]]\nname = "helper"\n')
        (self.root / "src/helper.toml").write_text(
            '[[module.export]]\nname = "helper"\n[[module.import]]\nname = "tb_first"\n'
        )
        with self.assertRaisesRegex(ConfigError, "cyclic source dependency"):
            configure(self.root, "xpr", "export")

    def test_project_schema_is_used_by_build_program_and_cleanup(self) -> None:
        text = self.original.replace('[[simulation]]\nid = "unfinished_simulation"\n', '')
        text = text.replace('xpr = "build/xpr"\n',
                            'xpr = "build/xpr"\nvvp = "build/vvp"\nvcd = "build/vcd"\n'
                            'synthesis = "build/synth"\nimplementation = "build/impl"\nbitstream = "build/bits"\n')
        text = text.replace('constraints = "board.xdc"\n',
                            'constraints = "board.xdc"\nsynthesis = "core.json"\n'
                            'implementation = "core.fasm"\nbitstream = "core.bit"\n')
        text = text.replace('timescale = "1ns/1ps"\n',
                            'timescale = "1ns/1ps"\nvvp = "first.vvp"\nvcd = "first.vcd"\n')
        text = text.replace('timescale = "10ns/1ps"\n',
                            'timescale = "10ns/1ps"\nvvp = "second.vvp"\nvcd = "second.vcd"\n')
        self.config.write_text(text)
        for command in ("synthesis", "implementation", "bitstream", "program"):
            with self.subTest(command=command):
                project = configure(self.root, command, "core")
                self.assertEqual([target.identifier for target in project.programs], ["core"])
                self.assertEqual(project.xprs, ())
        for command in ("build", "simulate"):
            self.assertEqual(configure(self.root, command, "first").simulations[0].top, "tb_first")
        for command in ("clean", "cleandist"):
            targets = configure(self.root, command).cleanup_targets
            self.assertEqual({target.identifier for target in targets}, {"core", "first", "second"})
        for command in ("auxiliary", "script"):
            project = configure(self.root, command)
            self.assertEqual(project.program_ids, ("core",))
            self.assertEqual(project.xprs, ())

    def test_completion_reads_xpr_ids_independently_of_projects(self) -> None:
        self.assertEqual(candidate_ids(self.config, "project"), ["core"])
        self.assertEqual(candidate_ids(self.config, "xpr"), ["export"])
        self.assertEqual(candidate_ids(self.config, "simulation"), ["first", "second", "unfinished_simulation"])

    def test_missing_dependency_has_an_actionable_error(self) -> None:
        stderr = io.StringIO()
        with patch.dict(sys.modules, {"pytcl": None}), redirect_stderr(stderr):
            result = main.main(["--project", str(self.root), "xpr", "export"])
        self.assertEqual(result, 1)
        self.assertIn("pytcl-eda", stderr.getvalue())
        self.assertIn("requirements.txt", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertFalse((self.root / "build/xpr").exists())
        self.assertTrue((self.root / "build/model").exists())

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_selected_export_uses_real_pytcl_and_quotes_paths(self) -> None:
        self.config.write_text(self.original + '[[xpr]]\nid = "unfinished"\nproject = "missing"\n')
        result = self.cli("xpr", "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        xpr = self.root / "build/xpr/export/export.xpr"
        self.assertTrue(xpr.is_file())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(calls[0], ["create_project", "-force", "export", str(xpr.parent),
                                    "-part", "xc7a35tcsg324-1"])
        files = [call for call in calls if call[0] == "add_files"]
        self.assertEqual(files, [
            ["add_files", "-norecurse", "-fileset", "sources_1", str(self.leaf)],
            ["add_files", "-norecurse", "-fileset", "sources_1", str(self.root / "src/top.v")],
            ["add_files", "-norecurse", "-fileset", "sources_1", str(self.root / "src/helper.sv")],
            ["add_files", "-norecurse", "-fileset", "constrs_1", str(self.root / "constraints/board.xdc")],
            ["add_files", "-norecurse", "-fileset", "sim_first", str(self.root / "sim/first.v")],
            ["add_files", "-norecurse", "-fileset", "sim_second", str(self.root / "sim/second.v")],
        ])
        self.assertIn(["set_property", "top", "top", "sources_1"], calls)
        self.assertIn(["set_property", "target_language", "Verilog", "export"], calls)
        for simulation, top, timescale in (("first", "tb_first", "1ns/1ps"), ("second", "tb_second", "10ns/1ps")):
            fileset = f"sim_{simulation}"
            self.assertIn(["create_fileset", "-simset", fileset], calls)
            self.assertIn(["set_property", "SOURCE_SET", "sources_1", fileset], calls)
            self.assertIn(["set_property", "top", top, fileset], calls)
            self.assertIn(["set_property", "xsim.elaborate.timescale", timescale, fileset], calls)
            self.assertIn(["update_compile_order", "-fileset", fileset], calls)
        self.assertIn(["current_fileset", "-simset", "sim_first"], calls)
        self.assertLess(calls.index(["current_fileset", "-simset", "sim_first"]),
                        calls.index(["delete_fileset", "sim_1"]))
        file_sets = json.loads(xpr.read_text())
        self.assertNotIn("sim_1", file_sets)
        self.assertEqual(file_sets["sim_second"], [str(self.root / "sim/second.v")])
        self.assertIn(str(self.root / "src/helper.sv"), file_sets["sources_1"])
        self.assertIn(str(self.leaf), file_sets["compile"]["sim_second"])
        self.assertTrue(any(call[:3] == ["set_property", "file_type", "SystemVerilog"] for call in calls))
        self.assertEqual(calls[-1], ["close_project"])
        self.assertFalse((self.root / "build/fpga").exists())
        self.assertFalse((self.root / "build/auxiliary").exists())
        self.assertFalse((self.root / "jobs.sh").exists())
        before = xpr.read_bytes(), xpr.stat().st_mtime_ns
        failed = self.cli("xpr")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual((xpr.read_bytes(), xpr.stat().st_mtime_ns), before)

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_simulation_top_from_sources_stays_in_design_fileset(self) -> None:
        self.config.write_text(self.original
                               .replace('top-symbol = "tb_first"', 'top-symbol = "top"')
                               .replace('simulations = ["first", "second"]', 'simulations = ["first"]'))
        result = self.cli("xpr", "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertIn(["set_property", "top", "top", "sim_first"], calls)
        self.assertFalse(any(call[:4] == ["add_files", "-norecurse", "-fileset", "sim_first"] for call in calls))
        file_sets = json.loads((self.root / "build/xpr/export/export.xpr").read_text())
        self.assertEqual(file_sets["compile"]["sim_first"], [str(self.leaf), str(self.root / "src/top.v")])

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_design_only_export_does_not_inherit_design_into_simulation(self) -> None:
        self.config.write_text(self.original.replace('simulations = ["first", "second"]', 'simulations = []'))
        result = self.cli("xpr", "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        file_sets = json.loads((self.root / "build/xpr/export/export.xpr").read_text())
        self.assertEqual(file_sets["sim_1"], [])
        self.assertEqual(file_sets["compile"]["sim_1"], [])

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_directory_roles_include_simulation_only_design_dependencies(self) -> None:
        (self.root / "src/only_sim.sv").write_text("module only_sim; endmodule\n")
        (self.root / "src/only_sim.toml").write_text('[[module.export]]\nname = "only_sim"\n')
        (self.root / "src/helper.toml").write_text(
            '[[module.export]]\nname = "helper"\n[[module.import]]\nname = "only_sim"\n'
        )
        (self.root / "sim/first.toml").write_text(
            '[[module.export]]\nname = "tb_first"\n[[module.import]]\nname = "helper"\n'
        )
        result = self.cli("xpr", "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        file_sets = json.loads((self.root / "build/xpr/export/export.xpr").read_text())
        self.assertEqual(set(file_sets["sources_1"]), {
            str(self.leaf), str(self.root / "src/top.v"), str(self.root / "src/helper.sv"),
            str(self.root / "src/only_sim.sv"),
        })
        self.assertEqual(file_sets["sim_first"], [str(self.root / "sim/first.v")])
        self.assertEqual(file_sets["sim_second"], [str(self.root / "sim/second.v")])
        for fileset in ("sim_first", "sim_second"):
            self.assertNotIn(str(self.root / "src/top.v"), file_sets["compile"][fileset])
        self.assertIn(str(self.root / "src/only_sim.sv"), file_sets["compile"]["sim_first"])
        self.assertIn(str(self.leaf), file_sets["compile"]["sim_second"])

    def test_design_cannot_depend_on_simulation_directory(self) -> None:
        (self.root / "src/top.toml").write_text(
            '[[module.export]]\nname = "top"\n[[module.import]]\nname = "tb_second"\n'
        )
        with self.assertRaisesRegex(ConfigError, "directories.simulation"):
            configure(self.root, "xpr", "export")
        self.assertFalse((self.root / "build").exists())

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_default_exports_all_xprs_and_regenerates_projects(self) -> None:
        self.config.write_text(self.original + (
            '[[fpga]]\nid = "other"\npart = "xc7a100tcsg324-1"\n'
            '[[project]]\nid = "other_core"\nfpga = "other"\ntop-symbol = "leaf"\nconstraints = "board.xdc"\n'
            '[[xpr]]\nid = "other_export"\nproject = "other_core"\n'
            '[[xpr]]\nid = "core"\nproject = "core"\nsimulations = []\n'
        ))
        for _ in range(2):
            result = self.cli("xpr")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "build/xpr/export/export.xpr").is_file())
        self.assertTrue((self.root / "build/xpr/other_export/other_export.xpr").is_file())
        self.assertTrue((self.root / "build/xpr/core/core.xpr").is_file())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        creates = [call for call in calls if call[0] == "create_project"]
        self.assertEqual([call[2] for call in creates], ["export", "other_export", "core"] * 2)
        self.assertEqual(creates[1][-1], "xc7a100tcsg324-1")

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_missing_vivado_and_tcl_errors_are_reported(self) -> None:
        self.vivado.rename(self.tools / "vivado.disabled")
        with patch("task.xpr.shutil.which", return_value=None):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = main.main(["--project", str(self.root), "xpr", "export"])
        self.assertEqual(result, 1)
        self.assertIn("Missing tool: vivado", stderr.getvalue())
        self.assertFalse((self.root / "build/xpr").exists())
        (self.tools / "vivado.disabled").rename(self.vivado)
        self.env["XPR_FAIL"] = "add_files"
        failed = self.cli("xpr", "export")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("non-zero status", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)


if __name__ == "__main__":
    unittest.main()
