"""Product summaries, managed cleanup, and generated entry contracts."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifacts import label, report, report_project
from layout import Layout
from models import Project
from planner import Planner
from task.clean import cleanup, remove_owned
from task.configure import configure
from task.model import build_model
from task.script import generate_script
from toolchains import select_toolchain
from util import ConfigError


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="products '[$] & ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src/top.v").write_text("module top; endmodule")
        (self.root / "src/top.toml").write_text('[[module.export]]\nname="top"\n')
        (self.root / "configuration.toml").write_text(
            'name="Products"\nid="workspace"\n[directories]\nsources=["src"]\n'
            '[[simulation]]\nid="first"\ntop-symbol="top"\n'
            '[[simulation]]\nid="second"\ntop-symbol="top"\n')

    def test_layout_defaults_and_shared_cleanup_paths(self):
        layout = Layout(self.root)
        project = configure(self.root, "build", "first")
        target, = project.simulations
        self.assertEqual(target.timescale, "1ns/1ps")
        self.assertEqual(target.vvp, self.root / "build/icarus/first/first.vvp")
        self.assertEqual(target.vcd, self.root / "build/icarus/first/first.vcd")
        self.assertEqual(layout.design("core", "bit"), self.root / "build/yosys/core/core.bit")
        self.assertEqual(layout.xpr("workspace"), self.root / "build/vivado/workspace/workspace.xpr")
        self.assertEqual(configure(self.root, "clean", "first").cleanup_targets[0].outputs,
                         (target.vvp, target.vcd))
        with self.assertRaises(ConfigError):
            layout.path("../../outside")

    def test_summary_absolute_existing_deduplicated_and_input_label(self):
        path = self.root / "a '$[].xdc"
        path.touch()
        entries = [(label("constraints", "core"), path)] * 2 + [("missing", path.with_suffix(".bit"))]
        output = io.StringIO()
        with redirect_stdout(output):
            report(entries)
        self.assertEqual(output.getvalue().splitlines(), [
            "=" * 60, f"The path of constraints (core, input): {path.resolve()}", "=" * 60])

    def test_build_omits_old_waveforms_and_failure_has_no_summary(self):
        project = configure(self.root, "build", "first")
        simulation, = project.simulations
        simulation.vvp.parent.mkdir(parents=True)
        simulation.vvp.touch()
        simulation.vcd.write_text("stale waveform")
        output = io.StringIO()
        with redirect_stdout(output):
            report_project(project, "first")
        self.assertIn("vvp (first)", output.getvalue())
        self.assertNotIn("vcd", output.getvalue())
        output = io.StringIO()
        with patch("task.build.execute_job", side_effect=ConfigError("injected failure")), \
                redirect_stdout(output), self.assertRaisesRegex(ConfigError, "injected failure"):
            Planner().run(self.root, "build", "first")
        self.assertNotIn("The path of", output.getvalue())

    def test_generated_simulation_removes_stale_vcd_before_running(self):
        select_toolchain(self.root, "vivado")
        project = build_model(configure(self.root, "script"))
        generate_script(project)
        script = (self.root / "build/jobs/first/simulate.sh").read_text(encoding="utf-8")
        self.assertLess(script.index("rm -f -- build/icarus/first/first.vcd"), script.index("vvp -N"))
        self.assertIn('BUILDSYS_REPORT_SUPPRESS=1', script)
        self.assertEqual(script.count("artifacts.py"), 1)
        dispatcher = project.script.read_text(encoding="utf-8")
        self.assertIn("xpr-simulation|xpr-synthesis", dispatcher)
        self.assertIn('exec python3', (self.root / "build/jobs/first/clean.sh").read_text())

    def test_target_clean_isolation_and_full_dist_preserves_settings_and_old_layout(self):
        for item in ("first", "second"):
            path = Layout(self.root).simulation(item, "vvp")
            path.parent.mkdir(parents=True)
            path.touch()
        settings = self.root / "build/fpga/board.toml"
        settings.parent.mkdir()
        settings.write_text("user settings")
        legacy = self.root / "build/vvp/old.vvp"
        legacy.parent.mkdir()
        legacy.touch()
        cleanup(configure(self.root, "clean", "first"), "first", dist=False)
        self.assertFalse(Layout(self.root).simulation("first", "vvp").exists())
        self.assertTrue(Layout(self.root).simulation("second", "vvp").exists())
        xpr = Layout(self.root).xpr("workspace")
        xpr.parent.mkdir(parents=True)
        xpr.touch()
        with patch("task.vivado.xpr_stage.run_stage", side_effect=AssertionError("must not start Vivado")):
            cleanup(configure(self.root, "cleandist"), None, dist=True)
        self.assertFalse(xpr.exists())
        self.assertEqual(settings.read_text(), "user settings")
        self.assertTrue(legacy.exists())

    def test_existing_xpr_requires_vivado_before_deleting_target(self):
        xpr = Layout(self.root).xpr("workspace")
        xpr.parent.mkdir(parents=True)
        xpr.touch()
        output = Layout(self.root).simulation("first", "vvp")
        output.parent.mkdir(parents=True)
        output.touch()
        with patch("task.vivado.xpr_stage.shutil.which", return_value=None), \
                self.assertRaisesRegex(ConfigError, "Missing tool: vivado"):
            cleanup(configure(self.root, "clean", "first"), "first", dist=False)
        self.assertTrue(output.exists())
        self.assertTrue(xpr.exists())

    def test_recursive_deletion_rejects_unmanaged_paths(self):
        project = Project(self.root, "workspace", (), ())
        with self.assertRaisesRegex(ConfigError, "outside managed"):
            remove_owned(project, self.root / "src")
        with self.assertRaisesRegex(ConfigError, "outside managed"):
            remove_owned(project, self.root / "build")
        self.assertTrue((self.root / "src/top.v").exists())


if __name__ == "__main__":
    unittest.main()
