"""Template substitution and generated shell syntax across supported backends."""

from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from models import CleanupTarget, Fpga, Program, Project, Simulation
from task.clean import cleanup_script
from task.install import install_wrappers
from task.script import generate_script
from util import ConfigError, render_template, write_template


BUILDSYS_DIR = Path(__file__).resolve().parents[1]
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")


class TemplateTests(unittest.TestCase):
    def test_replacement_is_literal_and_does_not_expand_inserted_arguments(self):
        template = '$(value)\n$(value)\n$(empty)\n$(cd -- "$(dirname "$0")" && pwd)\n${PATH}\n'
        value = "space 'quote' \\path $(other) $$(literal) \u4e2d\u6587"
        with patch("pathlib.Path.read_text", return_value=template):
            rendered = render_template("test.sh", value=value, empty="")
        self.assertEqual(rendered, f'{value}\n{value}\n\n$(cd -- "$(dirname "$0")" && pwd)\n${{PATH}}\n')

    def test_shell_command_substitution_can_be_escaped(self):
        with patch("pathlib.Path.read_text", return_value='$$(pwd) $$(name) $(name) $((1 + 2))\n'):
            self.assertEqual(render_template("test.sh", name="value"),
                             '$(pwd) $(name) value $((1 + 2))\n')

    def test_missing_arguments_report_the_template_and_parameter(self):
        with patch("pathlib.Path.read_text", return_value="$(missing)\n"):
            with self.assertRaisesRegex(ConfigError, r"test\.sh: missing template argument 'missing'"):
                render_template("test.sh")

    def test_writers_preserve_lf_and_batch_crlf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("pathlib.Path.read_text", return_value="$(value)\nlast\n"):
                write_template(root / "shell.sh", "test.sh", executable=True, value="line")
                write_template(root / "batch.bat", "test.bat", newline="\r\n", value="line")
            self.assertEqual((root / "shell.sh").read_bytes(), b"line\nlast\n")
            self.assertEqual((root / "batch.bat").read_bytes(), b"line\r\nlast\r\n")
            if os.name != "nt":
                self.assertTrue(os.access(root / "shell.sh", os.X_OK))

    @unittest.skipUnless(BASH and Path(BASH).is_file(), "Requires native Bash")
    def test_generated_scripts_parse_with_quoted_paths_and_empty_target_lists(self):
        with tempfile.TemporaryDirectory(dir=BUILDSYS_DIR if os.name == "nt" else None) as temporary:
            root = Path(temporary)
            output = root / "build/output '$(literal) & spaces"
            fpga = Fpga("board", "xc7a35tcsg324-1", root / "database '$(literal)",
                        (root / "tools '$(literal)",), (root / "modules '$(literal)",))
            simulation = Simulation("test", "tb$top", "1ns/1ps", output / "test.vvp", output / "test.vcd")
            program = Program("design", fpga, "top", output / "design.json", output / "design.fasm",
                              root / "constraints '$(literal).xdc", output / "design.bit")
            targets = (CleanupTarget("test", (simulation.vvp, simulation.vcd), root / "build/auxiliary/test.f"),
                       CleanupTarget("design", (program.synthesis, program.bitstream), root / "build/auxiliary/design.ys"))
            project = Project(root, "example", (simulation,), (program,), simulation_ids=("test",),
                              program_ids=("design",), cleanup_targets=targets, toolchain="yosys")
            install_wrappers(root)
            generate_script(project)
            for path in (root / "buildsys", root / "buildsys.sh", root / "jobs.sh", *root.glob("build/jobs/*/*.sh")):
                result = subprocess.run([BASH, "-n", path.as_posix()], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")
                self.assertNotIn(b"\r", path.read_bytes())
            self.assertIn("$(literal)", (root / "build/jobs/design/implementation.sh").read_text())
            for target, dist, temporary_script in ((None, True, True), ("test", False, False), ("design", True, False)):
                result = subprocess.run([BASH, "-n"], input="\n".join(cleanup_script(
                    project, target, dist=dist, temporary=temporary_script)), capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
            tools = root / "fake-tools"
            tools.mkdir()
            for name, marker in (("iverilog", "build-arguments"), ("vvp", "simulation-arguments")):
                tool = tools / name
                tool.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > {marker}\n',
                                encoding="utf-8", newline="\n")
                tool.chmod(0o755)
            project.filelist(simulation).parent.mkdir(parents=True, exist_ok=True)
            project.filelist(simulation).touch()
            env = dict(os.environ, PATH=f"{tools}{os.pathsep}{os.environ['PATH']}")
            result = subprocess.run([BASH, (root / "jobs.sh").as_posix(), "simulate", "test"],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "build-arguments").read_text().splitlines(), [
                "-g2012", "-Wall", "-s", "tb$top", "-f", "build/auxiliary/test.f",
                '-D__VCD_FILE__="build/output \'$(literal) & spaces/test.vcd"',
                "-o", "build/output '$(literal) & spaces/test.vvp",
            ])
            self.assertEqual((root / "simulation-arguments").read_text().splitlines(),
                             ["-N", "build/output '$(literal) & spaces/test.vvp"])
            for toolchain in ("yosys", "vivado"):
                generate_script(replace(project, simulations=(), programs=(), simulation_ids=(),
                                        program_ids=(), cleanup_targets=(), toolchain=toolchain))
                result = subprocess.run([BASH, "-n", (root / "jobs.sh").as_posix()],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
