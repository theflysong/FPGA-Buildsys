"""Behavior checks for project configuration, planning, and generated scripts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1] / "main.py"


class BuildSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "configuration.toml").write_text(
            'name = "Example"\nid = "example"\n'
            '[directories]\nsources = ["src"]\nvvp = "build/vvp"\nvcd = "build/vcd"\n'
            '[[simulation]]\nid = "demo"\ntop-symbol = "tb"\ntimescale = "1ns/1ps"\n'
            'vvp = "demo.vvp"\nvcd = "demo.vcd"\n'
        )
        (self.root / "src/core.v").write_text("module core; endmodule\n")
        (self.root / "src/core.toml").write_text('[[module.export]]\nname = "core"\n')
        (self.root / "src/tb.v").write_text(
            '`ifndef __VCD_FILE__\n`define __VCD_FILE__ "demo.vcd"\n`endif\n'
            'module tb; core dut(); initial begin $dumpfile(`__VCD_FILE__); '
            '$dumpvars(0, tb); #1 $finish; end endmodule\n'
        )
        (self.root / "src/tb.toml").write_text(
            '[[module.export]]\nname = "tb"\n[[module.import]]\nname = "core"\n'
        )

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ENTRY), "--project", str(self.root), *args],
            capture_output=True, text=True, check=False,
        )

    def dispatch(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.root / "jobs.sh"), *args],
            capture_output=True, text=True, check=False,
        )

    def add_second_simulation(self) -> None:
        with (self.root / "configuration.toml").open("a") as stream:
            stream.write(
                '[[simulation]]\nid = "second"\ntop-symbol = "tb_second"\n'
                'timescale = "1ns/1ps"\nvvp = "second.vvp"\nvcd = "second.vcd"\n'
            )
        (self.root / "src/second.v").write_text(
            '`ifndef __VCD_FILE__\n`define __VCD_FILE__ "second.vcd"\n`endif\n'
            'module tb_second; core dut(); initial begin $dumpfile(`__VCD_FILE__); '
            '$dumpvars(0, tb_second); #1 $finish; end endmodule\n'
        )
        (self.root / "src/second.toml").write_text(
            '[[module.export]]\nname = "tb_second"\n[[module.import]]\nname = "core"\n'
        )

    def add_program(self, *, mixed: bool = False) -> str:
        name = "prog_demo" if mixed else "coreprog"
        config = (
            'name = "FPGA example"\nid = "example"\n'
            '[directories]\nsources = ["src"]\n'
            'constraints = ["constraints"]\nsynthesis = "build/synth"\n'
            'implementation = "build/impl"\nbitstream = "build/bits"\n'
        )
        if mixed:
            config += (
                'vvp = "build/vvp"\nvcd = "build/vcd"\n'
                '[[simulation]]\nid = "demo"\ntop-symbol = "tb"\n'
                'timescale = "1ns/1ps"\nvvp = "demo.vvp"\nvcd = "demo.vcd"\n'
            )
        config += (
            '[[fpga]]\nid = "ego1"\npart = "xc7a35tcsg324-1"\n'
            f'[[program]]\nid = "{name}"\nfpga = "ego1"\n'
            'top-symbol = "core"\nsynthesis = "core.json"\n'
            'implementation = "core.fasm"\nbitstream = "core.bit"\n'
            'constraints = "board.xdc"\n'
        )
        (self.root / "configuration.toml").write_text(config)
        (self.root / "build/fpga").mkdir(parents=True)
        (self.root / "build/fpga/ego1.toml").write_text('xray-database = "database"\n')
        (self.root / "constraints").mkdir()
        (self.root / "constraints/board.xdc").write_text("# test constraints\n")
        (self.root / "database/xc7a35tcsg324-1").mkdir(parents=True)
        (self.root / "database/xc7a35tcsg324-1/part.yaml").write_text("{}\n")
        return name

    def test_program_only_stage_order(self) -> None:
        name = self.add_program()
        tool_dir = self.root / "fake-tools"
        tool_dir.mkdir()
        for tool, artifact in (
            ("yosys", "build/synth/core.json"),
            ("nextpnr-himbaechel", "build/impl/core.fasm"),
            ("fasm2frames", "build/bits/core.frames"),
            ("xc7frames2bit", "build/bits/core.bit"),
        ):
            script = tool_dir / tool
            if tool == "yosys":
                script.write_text(
                    '#!/usr/bin/env python3\nimport os, sys\nfrom pathlib import Path\n'
                    'with open(os.environ["CALL_LOG"], "a") as stream: stream.write("yosys\\n")\n'
                    'Path(sys.argv[sys.argv.index("-l") + 1]).write_text("yosys log\\n")\n'
                    "print('{\"modules\": {\"core\": {}}}')\n"
                )
            elif tool == "nextpnr-himbaechel":
                script.write_text(
                    '#!/usr/bin/env python3\nimport os, sys\nfrom pathlib import Path\n'
                    'with open(os.environ["CALL_LOG"], "a") as stream: stream.write("nextpnr-himbaechel\\n")\n'
                    'Path(sys.argv[sys.argv.index("--log") + 1]).write_text("nextpnr log\\n")\n'
                    f'Path("{artifact}").touch()\n'
                )
            else:
                script.write_text(
                    '#!/usr/bin/env bash\nset -eu\n'
                    f'printf "%s\\n" "{tool}" >> "$CALL_LOG"\n'
                    f'touch "{artifact}"\n'
                )
            script.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{tool_dir}:{env['PATH']}"
        env["CALL_LOG"] = str(self.root / "calls.log")
        command = [sys.executable, str(ENTRY), "--project", str(self.root)]
        for stage, expected in (
            ("synthesis", ["yosys"]),
            ("implementation", ["yosys", "nextpnr-himbaechel"]),
            ("bitstream", ["yosys", "nextpnr-himbaechel", "fasm2frames", "xc7frames2bit"]),
        ):
            (self.root / "calls.log").write_text("")
            result = subprocess.run([*command, stage, name], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.root / "calls.log").read_text().splitlines(), expected)
            for line in result.stderr.splitlines():
                if line.startswith(("Synthesis log: ", "Implementation log: ")):
                    log = Path(line.split(": ", 1)[1])
                    self.assertEqual(log.parents[1], Path("/dev/shm"))
                    self.assertTrue(log.is_file())
                    self.addCleanup(shutil.rmtree, log.parent)
        self.assertEqual((self.root / "build/synth/core.json").read_text(),
                         '{"modules":{"core":{}}}\n')
        self.assertFalse((self.root / "build/synth/coreprog.synthesis.log").exists())
        self.assertFalse((self.root / "build/impl/coreprog.implementation.log").exists())
        yosys_lines = (self.root / "build/aux/coreprog.ys").read_text().splitlines()
        self.assertLess(yosys_lines.index("synth_xilinx -family xc7 -top core"),
                        yosys_lines.index("hierarchy -top core -purge_lib"))
        self.assertLess(yosys_lines.index("hierarchy -top core -purge_lib"),
                        yosys_lines.index("write_json"))
        for stage in ("synthesis", "implementation", "bitstream"):
            job = self.root / f"build/jobs/{name}/{stage}.sh"
            self.assertTrue(job.is_file())
            self.assertEqual(subprocess.run(["bash", "-n", str(job)]).returncode, 0)
        self.assertFalse((self.root / "build/jobs/coreprog/build.sh").exists())
        self.assertIn("Unknown program", self.dispatch("bitstream", "missing").stderr)
        self.assertIn("unknown program", self.cli("bitstream", "missing").stderr)
        (tool_dir / "yosys").write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" yosys >> "$CALL_LOG"\n'
            'printf "invalid json\\n"\n'
        )
        broken = subprocess.run([*command, "synthesis", name], env=env,
                                capture_output=True, text=True)
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn("compact_json", broken.stderr)
        self.assertFalse((self.root / "build/synth/core.json").exists())
        for line in broken.stderr.splitlines():
            if line.startswith("Synthesis log: "):
                self.addCleanup(shutil.rmtree, Path(line.split(": ", 1)[1]).parent)
        (tool_dir / "yosys").write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" yosys >> "$CALL_LOG"\n'
            "printf '{\"modules\": {}}\\n'\nexit 7\n"
        )
        broken = subprocess.run([*command, "synthesis", name], env=env,
                                capture_output=True, text=True)
        self.assertNotEqual(broken.returncode, 0)
        self.assertFalse((self.root / "build/synth/core.json").exists())
        for line in broken.stderr.splitlines():
            if line.startswith("Synthesis log: "):
                self.addCleanup(shutil.rmtree, Path(line.split(": ", 1)[1]).parent)

    def test_mixed_project_and_program_config_errors(self) -> None:
        self.add_program(mixed=True)
        result = self.cli("script")
        self.assertEqual(result.returncode, 0, result.stderr)
        for job in ("build", "clean", "simulate"):
            self.assertTrue((self.root / f"build/jobs/demo/{job}.sh").exists())
        for job in ("synthesis", "implementation", "bitstream"):
            self.assertTrue((self.root / f"build/jobs/prog_demo/{job}.sh").exists())
        self.assertTrue((self.root / "build/aux/demo.f").exists())
        self.assertTrue((self.root / "build/aux/prog_demo.ys").exists())
        config_path = self.root / "configuration.toml"
        original = config_path.read_text()
        for needle, replacement, error in (
            ('fpga = "ego1"', 'fpga = "missing"', "unknown fpga id"),
            ('top-symbol = "core"', 'top-symbol = "missing"', "no exported top-symbol"),
            ('constraints = "board.xdc"', 'constraints = "missing.xdc"', "constraints file does not exist"),
            ('implementation = "core.fasm"', 'implementation = "core.json"', "duplicate output"),
        ):
            with self.subTest(error=error):
                changed = original.replace(needle, replacement)
                if error == "duplicate output":
                    changed = changed.replace('implementation = "build/impl"',
                                              'implementation = "build/synth"')
                config_path.write_text(changed)
                failure = self.cli("aux")
                self.assertNotEqual(failure.returncode, 0)
                self.assertIn(error, failure.stderr)
        config_path.write_text(original)

    def test_script_generates_aux_and_dispatches(self) -> None:
        script = self.cli("script")
        self.assertEqual(script.returncode, 0, script.stderr)
        self.assertEqual(script.stdout.splitlines(),
                         ["configure", "aux generation", "script generation"])
        self.assertTrue((self.root / "jobs.sh").is_file())
        self.assertFalse((self.root / "example.sh").exists())
        for task in ("build", "clean", "simulate"):
            self.assertTrue((self.root / f"build/jobs/demo/{task}.sh").is_file())
        self.assertEqual(json.loads((self.root / "build/aux/example.map").read_text()),
                         {"core": "src/core.v", "tb": "src/tb.v"})
        self.assertEqual(json.loads((self.root / "build/aux/example.dep").read_text()),
                         {"src/core.v": [], "src/tb.v": ["core"]})
        filelist = (self.root / "build/aux/demo.f").read_text()
        self.assertIn("+timescale+1ns/1ps", filelist)
        self.assertLess(filelist.index("src/core.v"), filelist.index("src/tb.v"))
        self.assertEqual(self.dispatch("build").returncode, 2)
        self.assertEqual(self.dispatch("clean", "demo", "extra").returncode, 2)
        unknown = self.dispatch("simulate", "missing")
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("Unknown simulation", unknown.stderr)
        self.assertNotEqual(self.cli("build").returncode, 0)

    def test_clean_and_cleandist_for_selected_and_all_targets(self) -> None:
        self.add_program(mixed=True)
        self.assertEqual(self.cli("script").returncode, 0)
        install = subprocess.run([sys.executable, str(ENTRY), "install", str(self.root)],
                                 capture_output=True, text=True)
        self.assertEqual(install.returncode, 0, install.stderr)
        outputs = (
            self.root / "build/vvp/demo.vvp",
            self.root / "build/vcd/demo.vcd",
            self.root / "build/synth/core.json",
            self.root / "build/impl/core.fasm",
            self.root / "build/bits/core.frames",
            self.root / "build/bits/core.bit",
        )
        for output in outputs:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("result")
        selected = self.cli("clean", "demo")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(selected.stdout.splitlines(), ["configure", "script generation", "script execution"])
        self.assertTrue(all(not output.exists() for output in outputs[:2]))
        self.assertTrue(all(output.exists() for output in outputs[2:]))
        self.assertTrue((self.root / "build/aux/demo.f").exists())
        self.assertTrue((self.root / "build/jobs/demo/build.sh").exists())
        self.assertTrue((self.root / "jobs.sh").exists())

        selected_dist = self.cli("cleandist", "prog_demo")
        self.assertEqual(selected_dist.returncode, 0, selected_dist.stderr)
        self.assertEqual(selected_dist.stdout.splitlines(), ["configure", "script generation", "script execution"])
        self.assertTrue(all(not output.exists() for output in outputs[2:]))
        self.assertFalse((self.root / "build/aux/prog_demo.ys").exists())
        self.assertFalse((self.root / "build/jobs/prog_demo").exists())
        for shared in ("example.map", "example.dep", "demo.f"):
            self.assertTrue((self.root / "build/aux" / shared).exists())
        self.assertTrue((self.root / "build/jobs/demo/build.sh").exists())
        self.assertTrue((self.root / "jobs.sh").exists())
        missing_job = self.dispatch("synthesis", "prog_demo")
        self.assertEqual(missing_job.returncode, 2)
        self.assertIn("run buildsys script", missing_job.stderr)
        self.assertEqual(self.cli("script").returncode, 0)
        self.assertTrue((self.root / "build/aux/prog_demo.ys").exists())
        self.assertTrue((self.root / "build/jobs/prog_demo/synthesis.sh").exists())

        for output in outputs:
            output.write_text("result")
        cleaned = self.cli("clean")
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertEqual(cleaned.stdout.splitlines(), ["configure", "script generation", "script execution"])
        self.assertTrue(all(not output.exists() for output in outputs))
        self.assertTrue((self.root / "build/aux/example.map").exists())
        self.assertTrue((self.root / "build/jobs/demo/build.sh").exists())
        self.assertTrue((self.root / "jobs.sh").exists())

        dist = self.cli("cleandist")
        self.assertEqual(dist.returncode, 0, dist.stderr)
        self.assertEqual(dist.stdout.splitlines(), ["configure", "script generation", "script execution"])
        for generated in ("build/aux", "build/jobs", "jobs.sh"):
            self.assertFalse((self.root / generated).exists())
        for wrapper in ("buildsys", "buildsys.sh"):
            self.assertTrue((self.root / wrapper).exists())
        restored = subprocess.run([str(self.root / "buildsys"), "script"],
                                  capture_output=True, text=True)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertTrue((self.root / "build/jobs/prog_demo/synthesis.sh").exists())

    def test_dispatcher_cleanup_is_shell_only_and_can_remove_itself(self) -> None:
        self.add_program(mixed=True)
        self.assertEqual(self.cli("script").returncode, 0)
        outputs = ("build/vvp/demo.vvp", "build/vcd/demo.vcd", "build/synth/core.json",
                   "build/impl/core.fasm", "build/bits/core.frames", "build/bits/core.bit")
        for relative in outputs:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("result")
        selected = self.dispatch("clean", "prog_demo")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertTrue((self.root / outputs[0]).exists())
        self.assertTrue(all(not (self.root / path).exists() for path in outputs[2:]))
        dist = self.dispatch("cleandist", "prog_demo")
        self.assertEqual(dist.returncode, 0, dist.stderr)
        self.assertFalse((self.root / "build/jobs/prog_demo").exists())
        self.assertTrue((self.root / "jobs.sh").exists())
        # Project scripts are independent of the target scripts that were removed.
        project_clean = self.dispatch("clean")
        self.assertEqual(project_clean.returncode, 0, project_clean.stderr)
        self.assertFalse((self.root / outputs[0]).exists())
        project_dist = self.dispatch("cleandist")
        self.assertEqual(project_dist.returncode, 0, project_dist.stderr)
        for path in ("jobs.sh", "build/aux", "build/jobs"):
            self.assertFalse((self.root / path).exists())
        # Python generates only a transient shell task; absent project scripts stay absent.
        pending = set(Path("/dev/shm").glob("buildsys-clean-*.sh"))
        (self.root / outputs[0]).write_text("result")
        transient = self.cli("clean", "demo")
        self.assertEqual(transient.returncode, 0, transient.stderr)
        self.assertFalse((self.root / outputs[0]).exists())
        for path in ("jobs.sh", "build/aux", "build/jobs"):
            self.assertFalse((self.root / path).exists())
        self.assertEqual(set(Path("/dev/shm").glob("buildsys-clean-*.sh")), pending)

    def test_task_id_validation_and_unknown_cleanup_target(self) -> None:
        self.add_program(mixed=True)
        config = self.root / "configuration.toml"
        original = config.read_text()
        cases = (
            (original.replace('id = "prog_demo"', 'id = "demo"'), "duplicate task id"),
            (original.replace('id = "prog_demo"', 'name = "prog_demo"'), "name is obsolete"),
            (original.replace('id = "prog_demo"', 'id = "prog_demo"\nname = "legacy"'),
             "name is obsolete"),
            (original.replace('id = "prog_demo"\n', ''), "id must be a nonempty string"),
        )
        for changed, error in cases:
            with self.subTest(error=error):
                config.write_text(changed)
                result = self.cli("aux")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertIn(str(config), result.stderr)
        config.write_text(original)
        for command in ("clean", "cleandist"):
            unknown = self.cli(command, "missing")
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("unknown target id", unknown.stderr)
        self.assertEqual(self.cli("script").returncode, 0)
        config.write_text(original.replace('id = "demo"', 'name = "demo"'))
        old_simulation = self.cli("aux")
        self.assertNotEqual(old_simulation.returncode, 0)
        self.assertIn("name is obsolete", old_simulation.stderr)

    def test_install_wrappers_forward_to_project(self) -> None:
        install = subprocess.run(
            [sys.executable, str(ENTRY), "install", "buildsys", str(self.root)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(install.returncode, 0, install.stderr)
        for name in ("buildsys", "buildsys.sh"):
            wrapper = self.root / name
            self.assertTrue(wrapper.is_file())
            self.assertTrue(wrapper.stat().st_mode & 0o111)
        installed = subprocess.run(
            [str(self.root / "buildsys"), "script"],
            cwd="/tmp", capture_output=True, text=True, check=False,
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertTrue((self.root / "jobs.sh").exists())
        self.assertTrue((self.root / "build/aux/demo.f").exists())
        via_shell = subprocess.run(
            [str(self.root / "buildsys.sh"), "aux"],
            cwd="/tmp", capture_output=True, text=True, check=False,
        )
        self.assertEqual(via_shell.returncode, 0, via_shell.stderr)
        unknown = subprocess.run(
            [str(self.root / "buildsys"), "build", "missing"],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("unknown simulation", unknown.stderr)
        default_install = subprocess.run(
            [sys.executable, str(ENTRY), "install"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(default_install.returncode, 0, default_install.stderr)
        missing = subprocess.run(
            [sys.executable, str(ENTRY), "install", str(self.root / "absent")],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("install directory does not exist", missing.stderr)

    def test_invalid_configurations_have_locations(self) -> None:
        cases = (
            ("duplicate export", self.root / "src/tb.toml", '[[module.export]]\nname = "core"\n[[module.export]]\nname = "tb"\n'),
            ("unresolved import", self.root / "src/tb.toml", '[[module.export]]\nname = "tb"\n[[module.import]]\nname = "missing"\n'),
            ("no exported top-symbol", self.root / "configuration.toml", (self.root / "configuration.toml").read_text().replace('top-symbol = "tb"', 'top-symbol = "missing"')),
        )
        for error, path, content in cases:
            with self.subTest(error=error):
                original = path.read_text()
                path.write_text(content)
                result = self.cli("aux")
                path.write_text(original)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertIn(str(path), result.stderr)

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog unavailable")
    def test_selected_build_simulate_and_clean(self) -> None:
        self.add_second_simulation()
        build = self.cli("build", "demo")
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertEqual(build.stdout.splitlines()[:4],
                         ["configure", "aux generation", "script generation", "script execution"])
        self.assertTrue((self.root / "build/vvp/demo.vvp").exists())
        self.assertFalse((self.root / "build/vvp/second.vvp").exists())
        for name in ("demo", "second"):
            for task in ("build", "clean", "simulate"):
                self.assertTrue((self.root / f"build/jobs/{name}/{task}.sh").exists())

        unknown = self.cli("simulate", "missing")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("unknown simulation", unknown.stderr)
        second_build = self.dispatch("build", "second")
        self.assertEqual(second_build.returncode, 0, second_build.stderr)
        self.assertTrue((self.root / "build/vvp/second.vvp").exists())

        first_simulation = self.dispatch("simulate", "demo")
        self.assertEqual(first_simulation.returncode, 0, first_simulation.stderr)
        self.assertTrue((self.root / "build/vcd/demo.vcd").exists())
        self.assertFalse((self.root / "build/vcd/second.vcd").exists())
        first_clean = self.dispatch("clean", "demo")
        self.assertEqual(first_clean.returncode, 0, first_clean.stderr)
        self.assertFalse((self.root / "build/vvp/demo.vvp").exists())
        self.assertFalse((self.root / "build/vcd/demo.vcd").exists())
        self.assertTrue((self.root / "build/vvp/second.vvp").exists())
        self.assertTrue((self.root / "build/jobs/demo/build.sh").exists())

        second_simulation = self.cli("simulate", "second")
        self.assertEqual(second_simulation.returncode, 0, second_simulation.stderr)
        self.assertTrue((self.root / "build/vcd/second.vcd").exists())
        second_clean = self.dispatch("clean", "second")
        self.assertEqual(second_clean.returncode, 0, second_clean.stderr)
        self.assertFalse((self.root / "build/vvp/second.vvp").exists())
        self.assertFalse((self.root / "build/vcd/second.vcd").exists())
        self.assertTrue((self.root / "build/aux/second.f").exists())


if __name__ == "__main__":
    unittest.main()
