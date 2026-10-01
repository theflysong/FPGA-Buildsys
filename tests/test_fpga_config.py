"""Exercise user-owned FPGA settings and builds before and after configuration."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1] / "main.py"


class FpgaConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="fpga local settings ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.local = self.root / "build/fpga/ego1.toml"
        self.config = self.root / "configuration.toml"
        (self.root / "src").mkdir()
        (self.root / "constraints").mkdir()
        (self.root / "constraints/board.xdc").write_text("# test constraints\n")
        (self.root / "src/core.v").write_text("module core; endmodule\n")
        (self.root / "src/core.toml").write_text('[[module.export]]\nname = "core"\n')
        (self.root / "src/tb.v").write_text(
            'module tb; core dut(); initial begin $dumpfile(`__VCD_FILE__); '
            '$dumpvars(0, tb); #1 $finish; end endmodule\n'
        )
        (self.root / "src/tb.toml").write_text(
            '[[module.export]]\nname = "tb"\n[[module.import]]\nname = "core"\n'
        )
        self.config.write_text(
            'name = "Mixed project"\nid = "mixed"\n'
            '[directories]\nsources = ["src"]\nconstraints = ["constraints"]\n'
            'vvp = "build/vvp"\nvcd = "build/vcd"\n'
            'synthesis = "build/synth"\nimplementation = "build/impl"\nbitstream = "build/bits"\n'
            '[[simulation]]\nid = "demo"\ntop-symbol = "tb"\ntimescale = "1ns/1ps"\n'
            'vvp = "demo.vvp"\nvcd = "demo.vcd"\n'
            '[[fpga]]\nid = "ego1"\npart = "xc7a35tcsg324-1"\n'
            '[[program]]\nid = "main"\nfpga = "ego1"\ntop-symbol = "core"\n'
            'synthesis = "main.json"\nimplementation = "main.fasm"\n'
            'bitstream = "main.bit"\nconstraints = "board.xdc"\n'
        )

    def cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(ENTRY), "--project", str(self.root), *args],
            capture_output=True, text=True, env=env,
        )
        for line in result.stderr.splitlines():
            if line.startswith(("Synthesis log: ", "Implementation log: ")):
                self.addCleanup(shutil.rmtree, Path(line.split(": ", 1)[1]).parent)
        return result

    def fake_tools(self) -> dict[str, str]:
        tools = self.root / "tools"
        tools.mkdir()
        for name in ("yosys", "nextpnr-himbaechel", "fasm2frames", "xc7frames2bit"):
            path = tools / name
            body = '#!/bin/sh\nprintf "%s\\n" "$0" >> "$CALL_LOG"\n'
            body += "printf '%s\\n' '{\"modules\": {}}'\n" if name == "yosys" else "exit 99\n"
            path.write_text(body)
            path.chmod(0o755)
        return dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}", CALL_LOG=str(self.root / "calls"))

    def test_first_configure_creates_private_template_only_once(self) -> None:
        original = self.config.read_bytes()
        result = self.cli("aux")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.local), result.stderr)
        self.assertIn("toolchain-root is optional", result.stderr)
        self.assertEqual(self.local.stat().st_mode & 0o777, 0o600)
        self.assertIn('xray-database = ""', self.local.read_text())
        self.assertIn('toolchain-root = []', self.local.read_text())
        self.assertEqual(self.config.read_bytes(), original)
        self.assertTrue((self.root / "build/aux/main.ys").is_file())
        self.assertTrue((self.root / "build/aux/demo.f").is_file())
        before = self.local.read_bytes(), self.local.stat().st_mtime_ns
        again = self.cli("script")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertNotIn("Created", again.stderr)
        self.assertEqual((self.local.read_bytes(), self.local.stat().st_mtime_ns), before)

    def test_pending_fpga_builds_stop_before_tools_in_both_entries(self) -> None:
        env = self.fake_tools()
        generated = self.cli("script", env=env)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        for command in ("synthesis", "implementation", "bitstream"):
            result = self.cli(command, "main", env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout.splitlines(), ["configure"])
            self.assertIn(str(self.local), result.stderr)
            direct = subprocess.run([str(self.root / "jobs.sh"), command, "main"],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(direct.returncode, 2, direct.stderr)
            self.assertIn("Fill xray-database", direct.stderr)
            self.assertIn("regenerate scripts", direct.stderr)
        self.assertFalse((self.root / "calls").exists())
        self.assertFalse((self.root / "build/synth").exists())

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus unavailable")
    def test_simulation_runs_before_local_fpga_paths_are_filled(self) -> None:
        result = self.cli("simulate", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "build/vvp/demo.vvp").is_file())
        self.assertTrue((self.root / "build/vcd/demo.vcd").is_file())
        clean = self.cli("clean")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertTrue(self.local.is_file())
        self.assertFalse((self.root / "build/vvp/demo.vvp").exists())

    def test_settings_paths_and_only_selected_fpga_blocks_build(self) -> None:
        with self.config.open("a") as stream:
            stream.write(
                '[[fpga]]\nid = "other"\npart = "xc7a35tcsg324-1"\n'
                '[[program]]\nid = "other_main"\nfpga = "other"\ntop-symbol = "core"\n'
                'synthesis = "other.json"\nimplementation = "other.fasm"\n'
                'bitstream = "other.bit"\nconstraints = "board.xdc"\n'
            )
        self.local.parent.mkdir(parents=True)
        toolchain = self.root / "toolchain with spaces"
        toolchain.mkdir()
        self.local.write_text(f'xray-database = "database"\ntoolchain-root = ["{toolchain}"]\n')
        env = self.fake_tools()
        result = self.cli("synthesis", "main", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "build/synth/main.json").read_text(), '{"modules":{}}\n')
        script = (self.root / "build/jobs/main/synthesis.sh").read_text()
        self.assertIn(str(self.root / "database"), script)
        self.assertIn(str(toolchain), script)
        self.assertEqual((self.root / "build/fpga/other.toml").stat().st_mode & 0o777, 0o600)
        calls = (self.root / "calls").read_bytes()
        pending = self.cli("synthesis", "other_main", env=env)
        self.assertNotEqual(pending.returncode, 0)
        self.assertIn("other.toml", pending.stderr)
        self.assertEqual((self.root / "calls").read_bytes(), calls)
        # Reload an absolute database path and a relative toolchain path.
        self.local.write_text(f'xray-database = "{self.root / "database"}"\ntoolchain-root = ["toolchain with spaces"]\n')
        self.assertEqual(self.cli("script").returncode, 0)
        self.assertIn(str(toolchain), (self.root / "build/jobs/main/synthesis.sh").read_text())

    def test_tools_are_found_in_root_and_bin(self) -> None:
        self.local.parent.mkdir(parents=True)
        for index, layout in enumerate((".", "bin")):
            with self.subTest(layout=layout):
                toolchain = self.root / f"toolchain with spaces {index}"
                tool_dir = toolchain / layout
                tool_dir.parent.mkdir(parents=True, exist_ok=True)
                env = self.fake_tools()
                (self.root / "tools").rename(tool_dir)
                # Use only the configured search paths to locate the fake tools.
                env["PATH"] = os.environ["PATH"]
                (tool_dir / "nextpnr-himbaechel").write_text(
                    '#!/bin/sh\nprintf "%s\\n" "$0" >> "$CALL_LOG"\n'
                    'for arg do case "$arg" in fasm=*) '
                    'printf "# fake FASM\\n" > "${arg#fasm=}" ;; esac; done\n'
                )
                self.local.write_text(
                    f'xray-database = "database"\ntoolchain-root = ["{toolchain}"]\n'
                )
                calls = self.root / "calls"
                calls.unlink(missing_ok=True)
                result = self.cli("implementation", "main", env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls.read_text().splitlines(), [
                    str(tool_dir / "yosys"), str(tool_dir / "nextpnr-himbaechel"),
                ])
                self.assertEqual((self.root / "build/impl/main.fasm").read_text(), "# fake FASM\n")

    def test_multiple_roots_supply_different_tools_in_list_order(self) -> None:
        self.local.parent.mkdir(parents=True)
        first = self.root / "first root"
        second = self.root / "second root"
        first.mkdir()
        (second / "bin").mkdir(parents=True)
        env = self.fake_tools()
        (self.root / "tools/yosys").rename(first / "yosys")
        # A lower-priority Yosys must not override the first root's executable.
        (second / "bin/yosys").write_text('#!/bin/sh\nexit 98\n')
        (second / "bin/yosys").chmod(0o755)
        nextpnr = second / "bin/nextpnr-himbaechel"
        nextpnr.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0" >> "$CALL_LOG"\n'
            'for arg do case "$arg" in fasm=*) '
            'printf "# fake FASM\\n" > "${arg#fasm=}" ;; esac; done\n'
        )
        nextpnr.chmod(0o755)
        env["PATH"] = os.environ["PATH"]
        self.local.write_text(
            'xray-database = "database"\n'
            'toolchain-root = ["first root", "second root"]\n'
        )
        result = self.cli("implementation", "main", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "calls").read_text().splitlines(),
                         [str(first / "yosys"), str(nextpnr)])

    def test_search_paths_only_add_root_and_bin_and_preserve_environment(self) -> None:
        self.local.parent.mkdir(parents=True)
        first = self.root / "first root"
        second = self.root / "second root"
        for root in (first, second):
            (root / "src/prjxray").mkdir(parents=True)
            (root / "install/bin").mkdir(parents=True)
            (root / "venv/bin").mkdir(parents=True)
        self.local.write_text(
            'xray-database = "database"\n'
            'toolchain-root = ["first root", "second root"]\n'
        )
        result = self.cli("script")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = (self.root / "build/jobs/main/synthesis.sh").read_text().splitlines()
        begin = next(i for i, line in enumerate(lines) if line.startswith("TOOLCHAIN_ROOTS="))
        end = next(i for i, line in enumerate(lines) if line.startswith("yosys_script="))
        setup = lines[begin:end]
        env = dict(os.environ, PYTHONPATH="existing packages")
        probe = subprocess.run(
            ["bash", "-c", "\n".join(["set -euo pipefail", *setup,
                                     'printf "%s\\n" "$PATH" "$PYTHONPATH"'])],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.splitlines(), [
            f"{first}:{first}/bin:{second}:{second}/bin:{env['PATH']}",
            f"{first}/src/prjxray:{second}/src/prjxray:existing packages",
        ])
        # Omitting the optional list or leaving it empty uses PATH as supplied.
        for suffix in ("", "toolchain-root = []\n"):
            self.local.write_text('xray-database = "database"\n' + suffix)
            self.assertEqual(self.cli("script").returncode, 0)
            script = (self.root / "build/jobs/main/synthesis.sh").read_text()
            self.assertNotIn("export PATH=", script)
            self.assertNotIn("export PYTHONPATH=", script)

    def test_missing_listed_root_reports_its_path_before_tools(self) -> None:
        self.local.parent.mkdir(parents=True)
        self.local.write_text('xray-database = "database"\ntoolchain-root = ["missing root"]\n')
        env = self.fake_tools()
        result = self.cli("synthesis", "main", env=env)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Missing toolchain root: {self.root / 'missing root'}", result.stderr)
        direct = subprocess.run([str(self.root / "jobs.sh"), "synthesis", "main"],
                                env=env, capture_output=True, text=True)
        self.assertEqual(direct.returncode, 2, direct.stderr)
        self.assertIn(f"Missing toolchain root: {self.root / 'missing root'}", direct.stderr)
        self.assertFalse((self.root / "calls").exists())

    def test_cleanup_preserves_user_settings_and_completion_recovers_ids(self) -> None:
        self.local.parent.mkdir(parents=True)
        self.local.write_text('# user comment\nxray-database = "database"\ntoolchain-root = []\n')
        self.local.chmod(0o640)
        before = self.local.read_bytes(), self.local.stat().st_mtime_ns, self.local.stat().st_mode
        self.assertEqual(self.cli("script").returncode, 0)
        for args in (("clean", "main"), ("clean",), ("cleandist", "main"), ("cleandist",)):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.local.read_bytes(), self.local.stat().st_mtime_ns, self.local.stat().st_mode), before)
        self.assertFalse((self.root / "build/aux").exists())
        self.assertFalse((self.root / "build/jobs").exists())
        self.assertEqual(self.cli("completion", "simulate", "").stdout.splitlines(), ["demo"])
        self.assertEqual(self.cli("completion", "program", "").stdout.splitlines(), ["main"])
        self.assertFalse((self.root / "build/aux").exists())
        self.assertEqual(self.cli("script").returncode, 0)
        self.assertEqual((self.local.read_bytes(), self.local.stat().st_mtime_ns, self.local.stat().st_mode), before)

    def test_public_errors_and_legacy_fields_do_not_initialize_settings(self) -> None:
        original = self.config.read_text()
        for text, error in (
            (original.replace('part = "xc7a35tcsg324-1"', 'part = "xc7a35tcsg324-1"\nxray-database = "old"'), "move xray-database"),
            (original.replace('part = "xc7a35tcsg324-1"', 'part = "xc7a35tcsg324-1"\ntoolchain-root = "old"'), "move toolchain-root"),
            (original.replace('top-symbol = "core"', 'top-symbol = "missing"'), "no exported top-symbol"),
            (original.replace('fpga = "ego1"', 'fpga = "missing"'), "unknown fpga id"),
        ):
            self.config.write_text(text)
            result = self.cli("aux")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stderr)
            self.assertFalse(self.local.parent.exists())

    def test_output_directories_require_single_path_strings(self) -> None:
        original = self.config.read_text()
        for kind, directory in (
            ("vvp", "build/vvp"), ("vcd", "build/vcd"),
            ("synthesis", "build/synth"), ("implementation", "build/impl"),
            ("bitstream", "build/bits"),
        ):
            for value in ('["build/output"]', '[]', '["one", "two"]', '42', '""', '"   "', None):
                with self.subTest(kind=kind, value=value):
                    old = f'{kind} = "{directory}"\n'
                    replacement = f'{kind} = {value}\n' if value is not None else ""
                    self.config.write_text(original.replace(old, replacement))
                    result = self.cli("aux")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(str(self.config), result.stderr)
                    self.assertIn(f"directories.{kind} must be a nonempty path string", result.stderr)
                    self.assertFalse((self.root / "build").exists())
        self.config.write_text(original)
        self.assertEqual(self.cli("script").returncode, 0)
        self.assertTrue((self.root / "build/aux/demo.f").is_file())
        self.assertTrue((self.root / "build/aux/main.ys").is_file())

    def test_local_toml_and_field_types_are_validated(self) -> None:
        self.assertEqual(self.cli("aux").returncode, 0)
        for text, error in (
            ('xray-database = [', "ego1.toml"),
            ('xray-database = 42', "xray-database must be a string"),
            ('xray-database = "db"\ntoolchain-root = "old"', "toolchain-root must be a list"),
            ('xray-database = "db"\ntoolchain-root = ""', "toolchain-root must be a list"),
            ('xray-database = "db"\ntoolchain-root = 42', "toolchain-root must be a list"),
            ('xray-database = "db"\ntoolchain-root = [42]', "toolchain-root must be a list"),
            ('xray-database = "db"\ntoolchain-root = [""]', "toolchain-root must be a list"),
            ('xray-database = "db"\ntoolchain-root = ["   "]', "toolchain-root must be a list"),
        ):
            self.local.write_text(text)
            result = self.cli("aux")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(self.local), result.stderr)
            self.assertIn(error, result.stderr)
        self.local.write_text('xray-database = "   "\n')
        self.assertEqual(self.cli("script").returncode, 0)
        self.assertNotEqual(self.cli("synthesis", "main").returncode, 0)


if __name__ == "__main__":
    unittest.main()
