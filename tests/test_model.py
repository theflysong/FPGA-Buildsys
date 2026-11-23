"""Source collection and persisted inventory without HDL dependency analysis."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from models import Fpga, SynthesisProgram
from task.auxiliary import generate_auxiliary
from task.clean import cleanup
from task.configure import configure
from task.model import build_model, generate_model, source_filename
from toolchains import select_toolchain
from util import ConfigError, source_files


ENTRY = Path(__file__).resolve().parents[1] / "main.py"


class ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="buildsys-model-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        select_toolchain(self.root, "yosys")
        self.config = self.root / "configuration.toml"
        self.original = (
            'name="Source inventory"\nid="inventory"\n[directories]\n'
            'sources=["src"]\nsimulation=["sim"]\n'
            '[[simulation]]\nid="test"\ntop-symbol="tb"\n'
        )
        self.config.write_text(self.original, encoding="utf-8")
        self.write("src/top.v", "module top; leaf dut(); endmodule")
        self.write("src/nested/leaf.sv", "module leaf; endmodule")
        self.write("sim/test.v", "module tb; top dut(); endmodule")

    def write(self, name: str, content: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def cli(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(ENTRY), "--project", str(self.root), command],
                              capture_output=True, text=True, timeout=20)

    def test_recursive_inventory_includes_unreferenced_files_and_filters_extensions(self):
        self.write("src/unused.v", "module unused; endmodule")
        self.write("src/nested/other.SV", "module other; endmodule")
        for name in ("src/header.vh", "src/header.svh", "src/notes.txt", "outside.v"):
            self.write(name, "not a compilation unit")
        project = build_model(configure(self.root, "build", "test"))
        self.assertEqual(project.sources, (
            "sim/test.v", "src/nested/leaf.sv", "src/nested/other.SV", "src/top.v", "src/unused.v",
        ))
        generate_auxiliary(project)
        self.assertEqual(project.filelist(project.simulations[0]).read_text().splitlines()[3:],
                         list(project.sources))

    def test_overlapping_directories_are_deduplicated(self):
        self.config.write_text(self.original.replace('sources=["src"]',
                                                     'sources=["src", "src/nested", "src/."]'))
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources, ("sim/test.v", "src/nested/leaf.sv", "src/top.v"))

    def test_no_parser_or_source_content_reads_are_needed(self):
        for text in ("module top( ; endmodule", "module tb; missing dut(); endmodule",
                     "module leaf; top cyclic(); endmodule", '`include "absent.svh"'):
            with self.subTest(text=text):
                self.write("src/top.v", text)
                project = configure(self.root, "build", "test")
                with patch.dict(sys.modules, pyslang=None), \
                        patch.object(Path, "read_text", side_effect=AssertionError("HDL was read")):
                    project = build_model(project)
                self.assertIn("src/top.v", project.sources)

    def test_missing_top_symbol_is_passed_to_compiler(self):
        self.config.write_text(self.original.replace('top-symbol="tb"', 'top-symbol="absent"'))
        project = build_model(configure(self.root, "build", "test"))
        generate_auxiliary(project)
        self.assertIn("# top-symbol: absent", project.filelist(project.simulations[0]).read_text())

    def test_synthesis_uses_all_design_files_and_simulation_uses_both_directories(self):
        self.write("src/unreferenced.sv", "module unreferenced; endmodule")
        project = build_model(configure(self.root, "build", "test"))
        program = SynthesisProgram("design", Fpga("board", "part", None, (), ()), "top",
                                   self.root / "build/design.json")
        project = replace(project, toolchain="yosys", programs=(program,))
        generate_auxiliary(project)
        self.assertEqual(source_files(project),
                         ["src/nested/leaf.sv", "src/top.v", "src/unreferenced.sv"])
        yosys = project.yosys_script(program).read_text()
        for path in source_files(project):
            self.assertIn('"' + path + '"', yosys)
        self.assertNotIn("sim/test.v", yosys)
        self.assertIn("sim/test.v", project.filelist(project.simulations[0]).read_text())

    def test_model_command_needs_only_common_configuration(self):
        self.config.write_text(self.original.replace('top-symbol="tb"\n', '')
                               + '[[project]]\nid="unfinished"\n[[fpga]]\nid="board"\n')
        local = self.write(".buildsys/fpga/board.toml", "broken TOML [")
        before = local.read_bytes(), local.stat().st_mtime_ns
        result = self.cli("model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((local.read_bytes(), local.stat().st_mtime_ns), before)
        self.assertEqual(len(list((self.root / "build/model").glob("*.json"))), 3)
        self.assertFalse((self.root / "build/symbol").exists())
        self.assertFalse((self.root / "build/auxiliary").exists())

    def test_inventory_contains_paths_only_and_preserves_unchanged_timestamps(self):
        project = build_model(configure(self.root, "model"))
        generate_model(project)
        files = [project.model_dir / source_filename(path) for path in project.sources]
        for source, path in zip(project.sources, files):
            self.assertEqual(json.loads(path.read_text()), {"path": source})
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
        generate_model(build_model(configure(self.root, "build", "test")))
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}, before)

    def test_inventory_removes_stale_records_and_preserves_other_files(self):
        project = build_model(configure(self.root, "model"))
        generate_model(project)
        stale = self.write("build/model/" + source_filename("removed.v"), "{}")
        note = self.write("build/model/notes.json", "keep")
        (self.root / "src/top.v").unlink()
        generate_model(build_model(configure(self.root, "build", "test")))
        self.assertFalse(stale.exists())
        self.assertFalse((project.model_dir / source_filename("src/top.v")).exists())
        self.assertEqual(note.read_text(), "keep")

    def test_paths_with_spaces_and_unicode_survive_relocation(self):
        self.write("src/中文 path/test.v", "module extra; endmodule")
        project = build_model(configure(self.root, "model"))
        generate_model(project)
        other = replace(project, root=self.root / "relocated")
        generate_model(other)
        self.assertEqual({path.name: path.read_bytes() for path in project.model_dir.iterdir()},
                         {path.name: path.read_bytes() for path in other.model_dir.iterdir()})

    def test_configuration_stays_lazy_and_invalid_directories_report_locations(self):
        self.assertEqual(configure(self.root, "model").sources, ())
        self.config.write_text(self.original.replace('sources=["src"]', 'sources=["absent"]'))
        with self.assertRaisesRegex(ConfigError, "configuration.toml: source directory does not exist"):
            build_model(configure(self.root, "model"))
        self.config.write_text(self.original)
        for path in self.root.rglob("*.v"):
            path.unlink()
        (self.root / "src/nested/leaf.sv").unlink()
        with self.assertRaisesRegex(ConfigError, "no Verilog source files"):
            build_model(configure(self.root, "model"))

    def test_cleanup_preserves_shared_inventory_until_full_cleandist(self):
        self.assertEqual(self.cli("script").returncode, 0)
        project = configure(self.root, "cleandist")
        cleanup(project, "test", dist=True)
        self.assertTrue(project.model_dir.is_dir())
        cleanup(project, None, dist=True)
        self.assertFalse(project.model_dir.exists())


if __name__ == "__main__":
    unittest.main()
