"""Project selection, backend boundaries, and generated-job enforcement."""

from __future__ import annotations

import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from main import main
from task import COMMANDS
from task.configure import configure
from task.install import install_wrappers
from toolchains import STAGES, select_toolchain, selected_toolchain, selection_path


ENTRY = Path(__file__).resolve().parents[1] / "main.py"


class ToolchainTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="toolchain project ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "configuration.toml"
        self.original = 'name = "Mixed project"\nid = "example"\n[directories]\nsources = ["src"]\nsimulation = ["sim"]\nconstraints = ["constraints"]\n[[simulation]]\nid = "test"\ntop-symbol = "tb"\ntimescale = "1ns/1ps"\n[[fpga]]\nid = "board"\npart = "xc7a35tcsg324-1"\n[[project]]\nid = "core"\nfpga = "board"\ntop-symbol = "top"\nconstraints = "board.xdc"\n'
        self.config.write_text(self.original, encoding="utf-8")
        for directory in ("src", "sim", "constraints"):
            (self.root / directory).mkdir()
        (self.root / "src/top.v").write_text("module top; endmodule\n")
        (self.root / "src/top.toml").write_text('[[module.export]]\nname = "top"\n')
        (self.root / "sim/tb.v").write_text("module tb; top dut(); initial #1 $finish; endmodule\n")
        (self.root / "sim/tb.toml").write_text(
            '[[module.export]]\nname = "tb"\n[[module.import]]\nname = "top"\n'
        )
        (self.root / "constraints/board.xdc").write_text("# constraints\n")

    def cli(self, *arguments: str, root: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(ENTRY), "--project", str(root or self.root), *arguments],
            cwd=self.root.parent, capture_output=True, text=True, timeout=20,
        )

    def test_selection_is_persistent_queryable_and_does_not_configure(self) -> None:
        self.config.write_text("broken TOML [")
        for name in ("yosys", "vivado", "vivado", "yosys"):
            result = self.cli("toolchain", name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), name)
            self.assertEqual(json.loads(selection_path(self.root).read_text()), {"name": name})
            self.assertEqual(self.cli("toolchain").stdout.strip(), name)
        self.assertEqual(self.config.read_text(), "broken TOML [")
        self.assertFalse((self.root / "build").exists())
        self.assertFalse((self.root / "jobs.sh").exists())

    def test_missing_selection_is_reported_before_configuration(self) -> None:
        self.config.unlink()
        for arguments in (
            ("toolchain",), ("auxiliary",), ("script",), ("synthesis", "core"),
            ("implementation", "core"), ("bitstream", "core"),
            ("program", "core", "--protocol", "ft2232"), ("xpr",),
            *((f"yosys-{stage}", "core") for stage in STAGES if stage != "program"),
            ("yosys-program", "core", "--protocol", "ft2232"),
            *((f"xpr-{stage}", "export") for stage in (
                "simulation", "synthesis", "implementation", "bitstream", "program",
            )),
        ):
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No toolchain selected", result.stderr)
                self.assertIn("buildsys toolchain", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.root / ".buildsys").exists())
        self.assertFalse((self.root / "build").exists())

    def test_unknown_name_keeps_existing_selection(self) -> None:
        select_toolchain(self.root, "yosys")
        before = selection_path(self.root).read_bytes()
        result = self.cli("toolchain", "unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)
        self.assertEqual(selection_path(self.root).read_bytes(), before)

    def test_invalid_selection_has_recovery_instructions(self) -> None:
        select_toolchain(self.root, "yosys")
        for value in ("broken [", "[]", "null", '{}', '{"name": []}', '{"name": "other"}'):
            with self.subTest(value=value):
                selection_path(self.root).write_text(value)
                result = self.cli("script")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(selection_path(self.root)), result.stderr)
                self.assertIn("buildsys toolchain", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        result = self.cli("toolchain", "vivado")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(selected_toolchain(self.root), "vivado")
        self.assertFalse((self.root / "build").exists())

    def test_wrong_backend_never_generates_or_starts_a_task(self) -> None:
        for name, arguments, expected in (
            ("yosys", ("xpr",), "vivado"),
            ("yosys", ("xpr-synthesis", "export"), "vivado"),
            ("vivado", ("yosys-synthesis", "core"), "yosys"),
            ("vivado", ("yosys-program", "core", "--protocol", "ft2232"), "yosys"),
        ):
            with self.subTest(name=name, arguments=arguments):
                select_toolchain(self.root, name)
                result = self.cli(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"buildsys toolchain {expected}", result.stderr)
                self.assertFalse((self.root / "build").exists())
                self.assertFalse((self.root / "jobs.sh").exists())

    def test_projects_and_working_directories_do_not_share_selection(self) -> None:
        second = self.root / "other project"
        second.mkdir()
        self.assertEqual(self.cli("toolchain", "vivado").returncode, 0)
        self.assertEqual(self.cli("toolchain", "yosys", root=second).returncode, 0)
        self.assertEqual(self.cli("toolchain").stdout.strip(), "vivado")
        self.assertEqual(self.cli("toolchain", root=second).stdout.strip(), "yosys")
        result = subprocess.run([sys.executable, str(ENTRY), "toolchain"], cwd=second,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "yosys")

    def test_common_configuration_and_model_do_not_require_selection(self) -> None:
        for command, target in (("build", "test"), ("simulate", "test"),
                                ("clean", None), ("cleandist", None), ("model", None)):
            with self.subTest(command=command):
                self.assertIsNone(configure(self.root, command, target).toolchain)
        result = self.cli("model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / ".buildsys").exists())

    def test_yosys_generation_and_switch_do_not_delete_outputs(self) -> None:
        select_toolchain(self.root, "yosys")
        generated = self.cli("script")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        for path in ("build/jobs/core/synthesis.sh", "build/jobs/core/program.sh",
                     "build/auxiliary/core.ys", "build/auxiliary/test.f", "build/fpga/board.toml"):
            self.assertTrue((self.root / path).is_file(), path)
        bitstream = self.root / "build/yosys/core/core.bit"
        bitstream.parent.mkdir(parents=True)
        bitstream.write_bytes(b"keep")
        before = {path: path.read_bytes() for path in (self.root / "build").rglob("*") if path.is_file()}
        self.assertEqual(self.cli("toolchain", "vivado").returncode, 0)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(self.config.read_text(), self.original)

    def test_vivado_generation_does_not_need_yosys_project_fields(self) -> None:
        select_toolchain(self.root, "vivado")
        lines = [line for line in self.original.splitlines()
                 if not line.startswith(("synthesis =", "implementation =", "bitstream ="))]
        self.config.write_text("\n".join(lines) + "\n")
        for command in ("auxiliary", "script"):
            generated = self.cli(command)
            self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertTrue((self.root / "build/auxiliary/test.f").is_file())
        self.assertTrue((self.root / "build/jobs/test/build.sh").is_file())
        self.assertFalse((self.root / "build/auxiliary/core.ys").exists())
        self.assertFalse((self.root / "build/jobs/core/synthesis.sh").exists())
        self.assertFalse((self.root / "build/fpga").exists())
        self.assertFalse((self.root / "build/xpr").exists())

    @unittest.skipIf(os.name == "nt", "Bash syntax validation is tested in Linux")
    def test_vivado_design_without_simulations_generates_valid_dispatcher(self) -> None:
        select_toolchain(self.root, "vivado")
        start = self.original.index("[[simulation]]")
        end = self.original.index("[[fpga]]")
        self.config.write_text(self.original[:start] + self.original[end:])
        result = self.cli("script")
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = subprocess.run(["bash", "-n", str(self.root / "jobs.sh")],
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    @unittest.skipIf(os.name == "nt", "Generated FPGA jobs require a Linux Bash environment")
    def test_generated_jobs_reject_a_changed_or_missing_selection(self) -> None:
        select_toolchain(self.root, "yosys")
        self.assertEqual(self.cli("script").returncode, 0)
        for name in ("vivado", None):
            if name:
                select_toolchain(self.root, name)
            else:
                selection_path(self.root).unlink()
            for command in ([str(self.root / "jobs.sh"), "yosys-synthesis", "core"],
                            [str(self.root / "build/jobs/core/synthesis.sh")],
                            [str(self.root / "build/jobs/core/program.sh"), "--protocol", "ft2232"]):
                with self.subTest(name=name, command=command):
                    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("buildsys toolchain", result.stderr)
                    self.assertNotIn("Fill xray-database", result.stderr)

    @unittest.skipIf(os.name == "nt", "Bash wrapper integration is tested in Linux")
    def test_wrapper_selection_uses_its_project_from_another_directory(self) -> None:
        install_wrappers(self.root)
        result = subprocess.run([str(self.root / "buildsys"), "toolchain", "vivado"],
                                cwd=self.root.parent, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(selected_toolchain(self.root), "vivado")

    @unittest.skipUnless(os.name == "nt", "Batch wrappers require Windows cmd.exe")
    def test_batch_selection_uses_its_project_from_another_directory(self) -> None:
        install_wrappers(self.root)
        batch = self.root / "buildsys.bat"
        for arguments in ("toolchain vivado", "toolchain"):
            command = f'"{os.environ["COMSPEC"]}" /d /s /c ""{batch}" {arguments}"'
            result = subprocess.run(command, cwd=self.root.parent, capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "vivado")
        self.assertEqual(selected_toolchain(self.root), "vivado")

    @unittest.skipIf(os.name == "nt", "Cleanup integration requires Linux Bash and /dev/shm")
    def test_cleandist_preserves_project_selection(self) -> None:
        select_toolchain(self.root, "yosys")
        self.assertEqual(self.cli("script").returncode, 0)
        before = selection_path(self.root).read_bytes()
        result = self.cli("cleandist")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(selection_path(self.root).read_bytes(), before)
        self.assertFalse((self.root / "jobs.sh").exists())

    def test_backend_commands_use_their_own_packages(self) -> None:
        for command in (f"yosys-{stage}" for stage in STAGES):
            self.assertTrue(COMMANDS[command].__name__.startswith("task.yosys."))
        for command in ("xpr", "xpr-simulation", "xpr-synthesis", "xpr-implementation", "xpr-bitstream", "xpr-program"):
            self.assertTrue(COMMANDS[command].__name__.startswith("task.vivado."))

    def test_yosys_shared_and_explicit_stages_generate_and_execute_the_same_jobs(self) -> None:
        select_toolchain(self.root, "yosys")
        local = self.root / "build/fpga/board.toml"
        local.parent.mkdir(parents=True)
        local.write_text('xray-database = "database"\nPYTHONPATH = ["src"]\n')
        for stage in STAGES:
            for command in (stage, f"yosys-{stage}"):
                with self.subTest(command=command), \
                        patch(f"task.yosys.{stage}.execute_job") as execute, \
                        contextlib.redirect_stdout(io.StringIO()):
                    options = ["--protocol", "ft2232"] if stage == "program" else []
                    self.assertEqual(main(["--project", str(self.root), command, "core", *options]), 0)
                    project, actual_stage, target, task_args, _ = execute.call_args.args
                    self.assertEqual((project.command, actual_stage, target),
                                     (f"yosys-{stage}", stage, "core"))
                    self.assertEqual(task_args, tuple(options))
                    self.assertTrue((self.root / f"build/jobs/core/{stage}.sh").is_file())

    def test_program_options_and_help_follow_selected_toolchain(self) -> None:
        for name, required, rejected in (
            ("yosys", "--protocol", "--hw-server"),
            ("vivado", "--hw-server", "--protocol"),
        ):
            select_toolchain(self.root, name)
            result = self.cli("program", "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(required, result.stdout)
            self.assertNotIn(rejected, result.stdout)
        select_toolchain(self.root, "yosys")
        result = self.cli("program", "core")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--protocol", result.stderr)
        for name, options in (("yosys", ("--protocol", "ft2232", "--device", "xc7*")),
                              ("vivado", ("--protocol", "ft2232"))):
            select_toolchain(self.root, name)
            result = self.cli("program", "core", *options)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments", result.stderr)
        self.assertFalse((self.root / "build").exists())

    def test_stage_help_is_available_without_selection(self) -> None:
        for command in (*STAGES, *(f"yosys-{stage}" for stage in STAGES)):
            result = self.cli(command, "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(selection_path(self.root).exists())


if __name__ == "__main__":
    unittest.main()
