"""Run real CLI/Tcl stages against a fake native Vivado process."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from completion_ids import xpr_simulation_ids
from models import XprStageTarget
from planner import Planner
from task.configure import configure
from task.vivado.xpr_stage import execute
from toolchains import select_toolchain
from util import ConfigError


ENTRY = Path(__file__).resolve().parents[1] / "main.py"
FAKE = Path(__file__).with_name("fake_vivado_stage.py")
COMPLETE_SYNTH = dict(STATUS="synth_design Complete!", PROGRESS="100%", NEEDS_REFRESH="0")
COMPLETE_IMPL = dict(STATUS="route_design Complete!", PROGRESS="100%", NEEDS_REFRESH="0")
COMPLETE_BIT = dict(STATUS="write_bitstream Complete!", PROGRESS="100%", NEEDS_REFRESH="0")


class XprStageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="stages {$[literal]}; ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        select_toolchain(self.root, "vivado")
        self.config = self.root / "configuration.toml"
        self.original = '''id = "example"
name = "Existing XPR"
[directories]
xpr = "build/xpr"
[[project]]
id = "core"
[[simulation]]
id = "first"
[[simulation]]
id = "second"
[[simulation]]
id = "other"
[[xpr]]
id = "export"
project = "core"
simulations = ["first", "second"]
'''
        self.config.write_text(self.original, encoding="utf-8")
        self.xpr = self.root / "build/xpr/export/export.xpr"
        self.xpr.parent.mkdir(parents=True)
        self.xpr.write_text("existing project - never replace", encoding="utf-8")
        tools = tempfile.TemporaryDirectory(prefix="stage tools ")
        self.addCleanup(tools.cleanup)
        self.tools = Path(tools.name)
        launcher = self.tools / ("vivado.bat" if os.name == "nt" else "vivado")
        if os.name == "nt":
            launcher.write_text(f'@"{sys.executable}" "{FAKE}" %*\n', encoding="utf-8")
        else:
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
            launcher.chmod(0o755)
        self.calls_path = self.root / "calls.jsonl"
        self.env = dict(os.environ, PATH=f"{self.tools}{os.pathsep}{os.environ['PATH']}",
                        XPR_CALLS=str(self.calls_path))

    def cli(self, command, *args, state=None):
        self.calls_path.unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, "-B", str(ENTRY), "--project", str(self.root), command, "export", *args],
            cwd=self.root, env=dict(self.env, XPR_FAKE_STATE=json.dumps(state or {})),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(self.xpr.read_text(), "existing project - never replace")
        self.assertFalse((self.root / "build/model").exists())
        self.assertFalse((self.root / "build/fpga").exists())
        return result

    def calls(self, name=None):
        records = [json.loads(line) for line in self.calls_path.read_text(encoding="utf-8").splitlines()]
        return [row for row in records if name is None or row[0] == name]

    def succeeded(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls()[0], ["open_project", self.xpr.as_posix()])
        self.assertEqual(self.calls()[-1], ["close_project"])

    def bitstream(self):
        path = self.xpr.with_suffix(".runs") / "impl_1/top.bit"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"existing bitstream")
        return path

    def test_read_only_configuration_and_workflows(self):
        for command in ("simulation", "synthesis", "implementation", "bitstream", "program"):
            with self.subTest(command=command):
                project = configure(self.root, "xpr-" + command, "export")
                target, = project.xpr_stages
                self.assertIsInstance(target, XprStageTarget)
                self.assertEqual(target.xpr, self.xpr)
                self.assertEqual(project.xprs, ())
                self.assertEqual(project.source_directories, ())
                self.assertEqual(Planner.TASKS["xpr-" + command], ("configure", "xpr stage execution"))
        self.assertFalse((self.xpr.parent / ".buildsys").exists())

    def test_configuration_errors(self):
        with self.assertRaisesRegex(ConfigError, "unknown xpr"):
            configure(self.root, "xpr-synthesis", "missing")
        cases = (
            (self.original.replace('project = "core"', 'project = "first"'), "unknown project"),
            (self.original.replace('["first", "second"]', '["absent"]'), "unknown simulation"),
            (self.original.replace('["first", "second"]', '["first", "first"]'), "duplicate simulation"),
            (self.original + '[[xpr]]\nid="export"\n', "duplicate xpr"),
        )
        for config, error in cases:
            with self.subTest(error=error):
                self.config.write_text(config, encoding="utf-8")
                with self.assertRaisesRegex(ConfigError, error):
                    configure(self.root, "xpr-synthesis", "export")
        self.config.write_text(self.original, encoding="utf-8")
        self.xpr.unlink()
        with self.assertRaisesRegex(ConfigError, "buildsys xpr export first"):
            configure(self.root, "xpr-synthesis", "export")
        self.assertFalse((self.xpr.parent / ".buildsys").exists())

    def test_simulation_defaults_selection_full_runtime_and_waveforms(self):
        for args, fileset in (((), "sim_first"), (("second",), "sim_second")):
            with self.subTest(fileset=fileset):
                self.succeeded(self.cli("xpr-simulation", *args))
                self.assertIn(["set_property", "xsim.simulate.runtime", "all", fileset], self.calls())
                self.assertIn(["set_property", "xsim.simulate.log_all_signals", "true", fileset], self.calls())
                self.assertEqual(self.calls("launch_simulation"), [
                    ["launch_simulation", "-mode", "behavioral", "-simset", fileset]])
                self.assertEqual(len(self.calls("close_sim")), 1)
                self.assertFalse(self.calls("launch_runs"))

    def test_simulation_errors(self):
        result = self.cli("xpr-simulation", "other")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not belong", result.stderr)
        self.assertFalse(self.calls_path.exists())
        self.config.write_text(self.original.replace('["first", "second"]', '[]'), encoding="utf-8")
        result = self.cli("xpr-simulation")
        self.assertIn("no configured simulations", result.stderr)
        self.config.write_text(self.original, encoding="utf-8")
        result = self.cli("xpr-simulation", state={"missing_fileset": "sim_first"})
        self.assertIn("fileset 'sim_first' is missing", result.stderr)
        self.assertFalse(self.calls("launch_simulation"))
        result = self.cli("xpr-simulation", state={"simulation_fatal": True})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("testbench assertion failed", result.stderr)

    def test_run_dependencies_and_bitstream_chain(self):
        for stage, expected in (
            ("synthesis", [["launch_runs", "synth_1"]]),
            ("implementation", [["launch_runs", "synth_1"], ["launch_runs", "impl_1"]]),
            ("bitstream", [["launch_runs", "synth_1"], ["launch_runs", "impl_1"],
                           ["launch_runs", "impl_1", "-to_step", "write_bitstream"]]),
        ):
            with self.subTest(stage=stage):
                self.succeeded(self.cli("xpr-" + stage))
                self.assertEqual(self.calls("launch_runs"), expected)
                self.assertEqual(self.calls("wait_on_run"), [["wait_on_run", row[1]] for row in expected])
                self.assertEqual(self.calls("reset_run"), [["reset_run", row[1]] for row in expected[:2]])
        self.assertTrue(self.bitstream().is_file())

    def test_completed_runs_reuse_without_launch_or_reset(self):
        self.bitstream()
        for stage in ("synthesis", "implementation", "bitstream"):
            with self.subTest(stage=stage):
                self.succeeded(self.cli("xpr-" + stage, state={"runs": {
                    "synth_1": COMPLETE_SYNTH, "impl_1": COMPLETE_BIT}}))
                for command in ("reset_run", "launch_runs", "wait_on_run"):
                    self.assertFalse(self.calls(command))

    def test_failed_stale_and_incomplete_runs_reset_then_retry(self):
        for properties in (
            dict(STATUS="synth_design ERROR", PROGRESS="42%"),
            dict(COMPLETE_SYNTH, NEEDS_REFRESH="1"),
            dict(COMPLETE_SYNTH, PROGRESS="99%"),
            dict(COMPLETE_SYNTH, STATUS=""),
        ):
            with self.subTest(properties=properties):
                self.succeeded(self.cli("xpr-synthesis", state={"runs": {"synth_1": properties}}))
                self.assertEqual(self.calls("reset_run"), [["reset_run", "synth_1"]])
                self.assertEqual(self.calls("launch_runs"), [["launch_runs", "synth_1"]])

    def test_failed_write_bitstream_restarts_implementation(self):
        self.succeeded(self.cli("xpr-bitstream", state={"runs": {
            "synth_1": COMPLETE_SYNTH,
            "impl_1": dict(STATUS="write_bitstream ERROR", PROGRESS="90%"),
        }}))
        self.assertEqual(self.calls("reset_run"), [["reset_run", "impl_1"]])
        self.assertEqual(self.calls("launch_runs"), [
            ["launch_runs", "impl_1"], ["launch_runs", "impl_1", "-to_step", "write_bitstream"]])

    def test_missing_file_from_completed_bitstream_is_regenerated(self):
        self.succeeded(self.cli("xpr-bitstream", state={"runs": {
            "synth_1": COMPLETE_SYNTH, "impl_1": COMPLETE_BIT}}))
        self.assertEqual(self.calls("reset_run"), [["reset_run", "impl_1"]])
        self.assertEqual(self.calls("launch_runs"), [
            ["launch_runs", "impl_1", "-to_step", "write_bitstream"]])

    def test_run_failure_never_proceeds_to_dependent_stage(self):
        for state in ({"fail_run": "synth_1"}, {"after_wait": {"NEEDS_REFRESH": "1"}},
                      {"after_wait": {"STATUS": ""}}, {"after_wait": {"PROGRESS": "80%"}}):
            with self.subTest(state=state):
                result = self.cli("xpr-bitstream", state=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("did not complete synthesis successfully", result.stderr)
                self.assertEqual(self.calls("launch_runs"), [["launch_runs", "synth_1"]])
                self.assertEqual(self.calls()[-1], ["close_project"])
        result = self.cli("xpr-synthesis", state={"missing_run": "synth_1"})
        self.assertIn("Expected Vivado run 'synth_1'", result.stderr)

    def test_bitstream_absent_and_custom_reported_path(self):
        result = self.cli("xpr-bitstream", state={"omit_bitstream": True})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Bitstream file is missing", result.stderr)
        custom = self.root / "custom run {$[]};"
        self.succeeded(self.cli("xpr-bitstream", state={"directory": str(custom)}))
        self.assertTrue((custom / "top.bit").is_file())
        state = {"runs": {"synth_1": COMPLETE_SYNTH, "impl_1": dict(COMPLETE_BIT,
                 **{"PROGRAM.FILE": str(custom / "top.bit")})}}
        self.succeeded(self.cli("xpr-program", state=state))
        self.assertIn(["set_property", "PROGRAM.FILE", (custom / "top.bit").as_posix(), "xc7a35t_0"], self.calls())

    def test_program_defaults_glob_order_cleanup_and_no_builds(self):
        bitstream = self.bitstream()
        for args, server, selected in (
            ((), "localhost:3121", "xc7a35t_0"),
            (("--hw-server", "remote:3122/$[literal];", "--device", "xc7a100?_*"),
             "remote:3122/$[literal];", "xc7a100t_1"),
        ):
            with self.subTest(args=args):
                self.succeeded(self.cli("xpr-program", *args, state={"runs": {
                    "synth_1": COMPLETE_SYNTH, "impl_1": COMPLETE_BIT}}))
                self.assertIn(["connect_hw_server", "-url", server], self.calls())
                self.assertIn(["set_property", "PROGRAM.FILE", bitstream.as_posix(), selected], self.calls())
                operations = [row[0] for row in self.calls() if row[0] in {
                    "open_hw_manager", "connect_hw_server", "open_hw_target", "get_hw_devices",
                    "program_hw_devices", "refresh_hw_device", "close_hw_target",
                    "disconnect_hw_server", "close_hw_manager", "close_project"}]
                self.assertEqual(operations, ["open_hw_manager", "connect_hw_server", "open_hw_target",
                    "get_hw_devices", "program_hw_devices", "refresh_hw_device", "close_hw_target",
                    "disconnect_hw_server", "close_hw_manager", "close_project"])
                self.assertFalse(self.calls("launch_runs"))
                self.assertFalse(self.calls("reset_run"))

    def test_program_missing_or_stale_bitstream_never_touches_hardware(self):
        for state in ({}, {"runs": {"synth_1": COMPLETE_SYNTH, "impl_1": COMPLETE_BIT}},
                      {"runs": {"synth_1": COMPLETE_SYNTH,
                                "impl_1": dict(COMPLETE_BIT, NEEDS_REFRESH="1")}}):
            with self.subTest(state=state):
                result = self.cli("xpr-program", state=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("buildsys xpr-bitstream export first", result.stderr)
                self.assertFalse(self.calls("open_hw_manager"))
                self.assertFalse(self.calls("launch_runs"))

    def test_vivado_2018_hardware_manager_names(self):
        self.bitstream()
        self.succeeded(self.cli("xpr-program", state={"legacy_hw": True, "runs": {
            "synth_1": COMPLETE_SYNTH, "impl_1": COMPLETE_BIT}}))
        self.assertTrue(self.calls("open_hw"))
        self.assertTrue(self.calls("close_hw"))
        self.assertTrue(self.calls("program_hw_devices"))

    def test_stage_target_records_resolved_bitstream_after_success(self):
        bitstream = self.bitstream()
        project = configure(self.root, "xpr-bitstream", "export")
        env = dict(self.env, XPR_FAKE_STATE=json.dumps({"runs": {
            "synth_1": COMPLETE_SYNTH, "impl_1": COMPLETE_BIT}}))
        with patch.dict(os.environ, env):
            updated = execute(project, "export")
        self.assertEqual(updated.xpr_stages[0].bitstream, bitstream)

    def test_hardware_errors_and_cleanup(self):
        self.bitstream()
        for state, args, message in (
            ({"devices": []}, (), "No FPGA hardware devices"),
            ({}, ("--device", "absent*"), "No hardware device matches"),
            ({"fail": "connect_hw_server"}, (), "Cannot connect"),
            ({"fail": "open_hw_target"}, (), "Cannot open FPGA"),
            ({"fail": "program_hw_devices"}, (), "Programming FPGA device"),
            ({"fail": "refresh_hw_device"}, (), "injected Tcl failure"),
        ):
            with self.subTest(state=state):
                state = dict(state, runs={"synth_1": COMPLETE_SYNTH, "impl_1": COMPLETE_BIT})
                result = self.cli("xpr-program", *args, state=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.calls()[-1], ["close_project"])
                self.assertTrue(self.calls("close_hw_manager"))

    def test_tool_tcl_log_and_process_errors(self):
        project = configure(self.root, "xpr-synthesis", "export")
        with patch("task.vivado.xpr_stage.shutil.which", return_value=None):
            with self.assertRaisesRegex(ConfigError, "Missing tool: vivado"):
                execute(project, "export")
        for state, message in (
            ({"fail": "open_project"}, "injected Tcl failure"),
            ({"fail": "launch_runs"}, "injected Tcl failure"),
            ({"fail": "wait_on_run"}, "injected Tcl failure"),
            ({"fail": "close_project"}, "Cleanup failed"),
            ({"log": "ERROR: log-only failure\n"}, "log-only failure"),
            ({"exit_status": 9}, "exit status 9"),
        ):
            with self.subTest(state=state):
                result = self.cli("xpr-synthesis", state=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertTrue((self.xpr.parent / ".buildsys/synthesis.tcl").is_file())
                self.assertTrue((self.xpr.parent / ".buildsys/synthesis.log").is_file())

    def test_completion_only_lists_selected_xpr_simulations(self):
        self.assertEqual(xpr_simulation_ids(self.config, "export"), ["first", "second"])
        self.assertEqual(xpr_simulation_ids(self.config, "missing"), [])

    def test_bash_completion_with_native_shell(self):
        # Never resolve Windows' bash.exe alias, which can launch WSL.
        bash = Path("C:/Program Files/Git/bin/bash.exe") if os.name == "nt" else shutil.which("bash")
        if not bash or not Path(bash).is_file():
            self.skipTest("native Git Bash/Bash is unavailable")
        python = self.tools / "python3"
        python.write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8")
        python.chmod(0o755)
        script = ENTRY.parent / "completion.sh"
        for words, expected in (
            (("xpr-simulation", ""), ["export"]),
            (("xpr-synthesis", ""), ["export"]),
            (("xpr-implementation", ""), ["export"]),
            (("xpr-bitstream", ""), ["export"]),
            (("xpr-program", ""), ["export"]),
            (("xpr-simulation", "export", ""), ["first", "second"]),
            (("xpr-simulation", "export", "s"), ["second"]),
            (("xpr-program", "export", ""), ["--hw-server", "--device"]),
            (("xpr-program", "export", "--hw-server", ""), []),
            (("xpr-program", "export", "--device=xc7*", ""), ["--hw-server"]),
            (("xpr-program", "--hw-server", "remote:3121", ""), ["export"]),
        ):
            with self.subTest(words=words):
                result = subprocess.run([str(bash), str(script), str(self.root), "--", *words],
                                        env=self.env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)
        self.assertFalse(self.calls_path.exists())


if __name__ == "__main__":
    unittest.main()
