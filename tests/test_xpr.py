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
from models import XprProgram
from task.configure import configure
from util import ConfigError


ENTRY = Path(__file__).resolve().parents[1] / "main.py"
HAS_PYTCL = importlib.util.find_spec("pytcl") is not None
HAS_TCL = importlib.util.find_spec("tkinter") is not None

# Use real pytcl.Vivado and TCLCall serialization, backed by a Tcl interpreter
# implementing only Vivado's project commands. No FPGA tools or licenses are used.
FAKE_VIVADO = r'''#!/usr/bin/env python3
import json, os, sys, tkinter
from multiprocessing.connection import Listener
from pathlib import Path

tcl = tkinter.Tcl()
current = ""
project_file = None
sources = []

def record(name, *args):
    global current, project_file
    with open(os.environ["XPR_CALLS"], "a") as stream:
        stream.write(json.dumps([name, *args]) + "\n")
    if name == os.environ.get("XPR_FAIL"):
        return tcl.call("error", "simulated Vivado failure")
    if name == "create_project":
        current = args[1]
        directory = Path(args[2])
        directory.mkdir(parents=True, exist_ok=True)
        project_file = directory / (current + ".xpr")
    elif name == "add_files" and args[2] == "sources_1":
        sources.append(args[3])
    elif name == "get_filesets":
        return args[0]
    elif name == "get_files":
        return tuple(sources)
    elif name == "current_project":
        return current
    elif name == "close_project":
        project_file.write_text("<Project/>\n")
    return ""

for name in ("create_project", "add_files", "get_filesets", "get_files", "set_property",
             "current_project", "update_compile_order", "close_project"):
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
        (self.root / "constraints").mkdir()
        self.leaf = self.root / "src/leaf {$[literal]}.sv"
        self.leaf.write_text("module leaf; endmodule\n")
        self.leaf.with_suffix(".toml").write_text('[[module.export]]\nname = "leaf"\n')
        (self.root / "src/top.v").write_text("module top; leaf dut(); endmodule\n")
        (self.root / "src/top.toml").write_text(
            '[[module.export]]\nname = "top"\n[[module.import]]\nname = "leaf"\n'
        )
        (self.root / "constraints/board.xdc").write_text("# XDC\n")
        self.config = self.root / "configuration.toml"
        self.original = (
            'id = "example"\nname = "Vivado export"\n'
            '[directories]\nsources = ["src"]\nconstraints = ["constraints"]\nxpr = "build/xpr"\n'
            '[[fpga]]\nid = "board"\npart = "xc7a35tcsg324-1"\n'
            '[[program]]\nid = "core"\nfpga = "board"\ntop-symbol = "top"\nconstraints = "board.xdc"\n'
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
        self.config.write_text(self.original + '[[program]]\nid = "unfinished"\n')
        local = self.root / "build/fpga/board.toml"
        local.parent.mkdir(parents=True)
        local.write_text("invalid TOML [")
        project = configure(self.root, "xpr", "core")
        target, = project.programs
        self.assertIsInstance(target, XprProgram)
        self.assertEqual(target.xpr, self.root / "build/xpr/core/core.xpr")
        self.assertEqual(local.read_text(), "invalid TOML [")
        self.assertFalse((self.root / "build/xpr").exists())
        local.unlink()
        configure(self.root, "xpr", "core")
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
        )
        for text, message in cases:
            with self.subTest(message=message):
                self.config.write_text(text)
                with self.assertRaisesRegex(ConfigError, message):
                    configure(self.root, "xpr", "core")
                self.assertFalse((self.root / "build").exists())
        self.config.write_text(self.original)
        with self.assertRaisesRegex(ConfigError, "unknown program"):
            configure(self.root, "xpr", "unfinished_simulation")
        (self.root / "src/top.toml").write_text(
            '[[module.export]]\nname = "top"\n[[module.import]]\nname = "missing"\n'
        )
        with self.assertRaisesRegex(ConfigError, "unresolved import"):
            configure(self.root, "xpr", "core")

    def test_missing_dependency_has_an_actionable_error(self) -> None:
        stderr = io.StringIO()
        with patch.dict(sys.modules, {"pytcl": None}), redirect_stderr(stderr):
            result = main.main(["--project", str(self.root), "xpr", "core"])
        self.assertEqual(result, 1)
        self.assertIn("pytcl-eda", stderr.getvalue())
        self.assertIn("requirements.txt", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertFalse((self.root / "build").exists())

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_selected_export_uses_real_pytcl_and_quotes_paths(self) -> None:
        self.config.write_text(self.original + '[[program]]\nid = "unfinished"\n')
        result = self.cli("xpr", "core")
        self.assertEqual(result.returncode, 0, result.stderr)
        xpr = self.root / "build/xpr/core/core.xpr"
        self.assertTrue(xpr.is_file())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(calls[0], ["create_project", "-force", "core", str(xpr.parent),
                                    "-part", "xc7a35tcsg324-1"])
        files = [call for call in calls if call[0] == "add_files"]
        self.assertEqual(files, [
            ["add_files", "-norecurse", "-fileset", "sources_1", str(self.leaf)],
            ["add_files", "-norecurse", "-fileset", "sources_1", str(self.root / "src/top.v")],
            ["add_files", "-norecurse", "-fileset", "constrs_1", str(self.root / "constraints/board.xdc")],
        ])
        self.assertIn(["set_property", "top", "top", "sources_1"], calls)
        self.assertIn(["set_property", "target_language", "Verilog", "core"], calls)
        self.assertTrue(any(call[:3] == ["set_property", "file_type", "SystemVerilog"] for call in calls))
        self.assertEqual(calls[-2:], [["update_compile_order", "-fileset", "sources_1"], ["close_project"]])
        self.assertFalse((self.root / "build/fpga").exists())
        self.assertFalse((self.root / "build/auxiliary").exists())
        self.assertFalse((self.root / "jobs.sh").exists())
        before = xpr.read_bytes(), xpr.stat().st_mtime_ns
        failed = self.cli("xpr")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual((xpr.read_bytes(), xpr.stat().st_mtime_ns), before)

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_default_exports_all_programs_and_regenerates_projects(self) -> None:
        self.config.write_text(self.original + (
            '[[fpga]]\nid = "other"\npart = "xc7a100tcsg324-1"\n'
            '[[program]]\nid = "second"\nfpga = "other"\ntop-symbol = "leaf"\nconstraints = "board.xdc"\n'
        ))
        for _ in range(2):
            result = self.cli("xpr")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "build/xpr/core/core.xpr").is_file())
        self.assertTrue((self.root / "build/xpr/second/second.xpr").is_file())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        creates = [call for call in calls if call[0] == "create_project"]
        self.assertEqual([call[2] for call in creates], ["core", "second", "core", "second"])
        self.assertEqual(creates[1][-1], "xc7a100tcsg324-1")

    @unittest.skipUnless(HAS_PYTCL and HAS_TCL, "Install requirements.txt and tkinter for pytcl integration")
    def test_missing_vivado_and_tcl_errors_are_reported(self) -> None:
        self.vivado.rename(self.tools / "vivado.disabled")
        with patch("task.xpr.shutil.which", return_value=None):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = main.main(["--project", str(self.root), "xpr", "core"])
        self.assertEqual(result, 1)
        self.assertIn("Missing tool: vivado", stderr.getvalue())
        self.assertFalse((self.root / "build").exists())
        (self.tools / "vivado.disabled").rename(self.vivado)
        self.env["XPR_FAIL"] = "add_files"
        failed = self.cli("xpr", "core")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("non-zero status", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)


if __name__ == "__main__":
    unittest.main()
