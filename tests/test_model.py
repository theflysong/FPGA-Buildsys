"""Source models, dependency scoping, and persisted artifact behavior."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from task.auxiliary import generate_auxiliary
from task.clean import cleanup_script
from task.configure import configure
from task.model import build_model, generate_model
from toolchains import select_toolchain
from util import ConfigError, source_closure


ENTRY = Path(__file__).resolve().parents[1] / "main.py"


class ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="buildsys-model-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        select_toolchain(self.root, "yosys")
        (self.root / "src").mkdir()
        (self.root / "sim").mkdir()
        self.config = self.root / "configuration.toml"
        self.original = (
            'name = "Source graph"\nid = "graph"\n'
            '[directories]\nsources = ["src"]\nsimulation = ["sim"]\n'
            'vvp = "build/vvp"\nvcd = "build/vcd"\n'
            '[[simulation]]\nid = "test"\ntop-symbol = "tb"\ntimescale = "1ns/1ps"\n'
            'vvp = "test.vvp"\nvcd = "test.vcd"\n'
        )
        self.config.write_text(self.original, encoding="utf-8")
        self.source("src/leaf.v", ("leaf", "leaf_alias"))
        self.source("src/left.v", ("left",), ("leaf", "leaf_alias"))
        self.source("src/right.sv", ("right",), ("leaf",))
        self.source("sim/test.v", ("tb",), ("left", "right"))

    def source(self, path: str, exports: tuple[str, ...], imports: tuple[str, ...] = ()) -> None:
        source = self.root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("\n".join(f"module {name}; endmodule" for name in exports), encoding="utf-8")
        source.with_suffix(".toml").write_text(
            "".join(f'[[module.export]]\nname = "{name}"\n' for name in exports)
            + "".join(f'[[module.import]]\nname = "{name}"\n' for name in imports), encoding="utf-8",
        )

    def cli(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(ENTRY), "--project", str(self.root), command],
                              capture_output=True, text=True, timeout=20)

    def load(self, directory: str, path: str) -> dict:
        name = hashlib.sha256(path.encode("utf-8")).hexdigest() + ".json"
        return json.loads((self.root / "build" / directory / name).read_text(encoding="utf-8"))

    def test_model_command_needs_only_common_configuration_and_metadata(self) -> None:
        self.config.write_text(self.original.replace(
            'vvp = "build/vvp"\nvcd = "build/vcd"\n', ''
        ).replace('top-symbol = "tb"\ntimescale = "1ns/1ps"\n', '')
            + '[[project]]\nid = "unfinished"\n[[fpga]]\nid = "board"\n', encoding="utf-8")
        local = self.root / "build/fpga/board.toml"
        local.parent.mkdir(parents=True)
        local.write_text("broken TOML [", encoding="utf-8")
        before = local.read_bytes(), local.stat().st_mtime_ns
        result = self.cli("model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["configure", "model"])
        self.assertEqual((local.read_bytes(), local.stat().st_mtime_ns), before)
        self.assertEqual(len(list((self.root / "build/model").glob("*.json"))), 4)
        self.assertFalse((self.root / "build/auxiliary").exists())
        self.assertFalse((self.root / "jobs.sh").exists())

    def test_diamond_dependencies_symbols_and_topological_closure(self) -> None:
        project = build_model(configure(self.root, "model"))
        generate_model(project)
        self.assertEqual(self.load("symbol", "src/leaf.v"),
                         {"path": "src/leaf.v", "import": [], "export": ["leaf", "leaf_alias"]})
        self.assertEqual(self.load("model", "src/left.v"), {
            "path": "src/left.v", "dependencies": ["src/leaf.v"], "closure": ["src/leaf.v"],
        })
        self.assertEqual(self.load("model", "sim/test.v"), {
            "path": "sim/test.v", "dependencies": ["src/left.v", "src/right.sv"],
            "closure": ["src/leaf.v", "src/left.v", "src/right.sv"],
        })
        self.assertEqual(source_closure(project, "tb"),
                         ["src/leaf.v", "src/left.v", "src/right.sv", "sim/test.v"])

    def test_path_hashes_distinguish_same_basename_and_survive_relocation(self) -> None:
        self.source("src/nested/test.v", ("nested",))
        self.source("src/中文/test.v", ("unicode_module",))
        project = build_model(configure(self.root, "model"))
        generate_model(project)
        for source in ("src/nested/test.v", "src/中文/test.v", "sim/test.v"):
            self.assertEqual(self.load("symbol", source)["path"], source)
        other = self.root / "relocated"
        generate_model(replace(project, root=other))
        for directory in ("model", "symbol"):
            original = {path.name: path.read_bytes() for path in (self.root / "build" / directory).iterdir()}
            relocated = {path.name: path.read_bytes() for path in (other / "build" / directory).iterdir()}
            self.assertEqual(original, relocated)

    def test_overlapping_directories_and_legacy_sources_are_supported(self) -> None:
        for directories in ('sources = ["src", "sim", "src/."]\nsimulation = ["sim", "src"]',
                            'sources = ["src", "sim"]'):
            with self.subTest(directories=directories):
                self.config.write_text(self.original.replace(
                    'sources = ["src"]\nsimulation = ["sim"]', directories), encoding="utf-8")
                project = build_model(configure(self.root, "model"))
                self.assertEqual(len(project.sources), 4)
                self.assertEqual(project.exports["tb"], "sim/test.v")

    def test_full_generation_removes_only_stale_hash_json(self) -> None:
        self.assertEqual(self.cli("model").returncode, 0)
        stale_name = hashlib.sha256(b"removed.v").hexdigest() + ".json"
        for directory in ("model", "symbol"):
            (self.root / "build" / directory / stale_name).write_text("{}")
            (self.root / "build" / directory / "notes.json").write_text("keep")
        result = self.cli("model")
        self.assertEqual(result.returncode, 0, result.stderr)
        for directory in ("model", "symbol"):
            self.assertFalse((self.root / "build" / directory / stale_name).exists())
            self.assertEqual((self.root / "build" / directory / "notes.json").read_text(), "keep")

    def test_selected_generation_preserves_unrelated_artifacts(self) -> None:
        self.source("src/unused.v", ("unused",))
        self.assertEqual(self.cli("model").returncode, 0)
        filename = hashlib.sha256(b"src/unused.v").hexdigest() + ".json"
        paths = [self.root / "build" / directory / filename for directory in ("model", "symbol")]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        self.source("src/unused.v", ("unused",), ("missing",))
        project = build_model(configure(self.root, "build", "test"))
        generate_model(project)
        generate_auxiliary(project)
        self.assertNotIn("src/unused.v", project.sources)
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)
        self.assertEqual((self.root / "build/auxiliary/test.f").read_text().splitlines()[3:],
                         ["src/leaf.v", "src/left.v", "src/right.sv", "sim/test.v"])
        self.assertEqual(list((self.root / "build/auxiliary").iterdir()), [self.root / "build/auxiliary/test.f"])
        with self.assertRaisesRegex(ConfigError, "unresolved import"):
            build_model(configure(self.root, "model"))

    def test_unrelated_cycles_only_block_full_commands(self) -> None:
        self.source("src/cycle_a.v", ("cycle_a",), ("cycle_b",))
        self.source("src/cycle_b.v", ("cycle_b",), ("cycle_a",))
        build_model(configure(self.root, "build", "test"))
        for command in ("model", "auxiliary", "script"):
            with self.subTest(command=command), self.assertRaisesRegex(ConfigError, "cyclic source dependency"):
                build_model(configure(self.root, command))

    def test_reachable_missing_import_and_cycle_fail_without_outputs(self) -> None:
        for imported, message in (("missing", "unresolved import"), ("tb", "cyclic source dependency")):
            self.source("src/leaf.v", ("leaf", "leaf_alias"), (imported,))
            with self.subTest(imported=imported):
                result = self.cli("script")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertIn(".toml", result.stderr)
                self.assertFalse((self.root / "build").exists())

    def test_global_metadata_errors_block_selected_targets(self) -> None:
        self.source("src/unused.v", ("unused",))
        metadata = self.root / "src/unused.toml"
        for text, message in ((None, "unused.toml"), ("broken [", "unused.toml"),
                              ('[[module.export]]\nname = "tb"\n', "duplicate export")):
            with self.subTest(message=message):
                if text is None:
                    metadata.unlink()
                else:
                    metadata.write_text(text)
                with self.assertRaisesRegex(ConfigError, message):
                    build_model(configure(self.root, "build", "test"))

    def test_self_imports_do_not_create_file_dependencies(self) -> None:
        self.source("src/leaf.v", ("leaf", "leaf_alias"), ("leaf_alias",))
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources["src/leaf.v"].dependencies, ())
        self.assertEqual(project.sources["src/leaf.v"].closure, ())

    def test_configuration_does_not_scan_sources(self) -> None:
        (self.root / "src/leaf.toml").unlink()
        project = configure(self.root, "build", "test")
        self.assertEqual(project.sources, {})
        with self.assertRaisesRegex(ConfigError, "leaf.toml"):
            build_model(project)

    def test_cleanup_scripts_preserve_shared_models_except_full_cleandist(self) -> None:
        project = configure(self.root, "cleandist")
        for target, dist in ((None, False), ("test", False), ("test", True)):
            script = "\n".join(cleanup_script(project, target, dist=dist))
            self.assertNotIn("build/model", script)
            self.assertNotIn("build/symbol", script)
        script = "\n".join(cleanup_script(project, None, dist=True))
        self.assertIn("rm -rf -- build/model", script)
        self.assertIn("rm -rf -- build/symbol", script)

    def test_metadata_errors_precede_fpga_settings_initialization(self) -> None:
        (self.root / "constraints").mkdir()
        (self.root / "constraints/board.xdc").write_text("# constraints")
        self.config.write_text(self.original.replace('[directories]\n',
            '[directories]\nconstraints = ["constraints"]\nsynthesis = "build/synth"\n'
            'implementation = "build/impl"\nbitstream = "build/bits"\n')
            + '[[fpga]]\nid = "board"\npart = "xc7a35tcsg324-1"\n'
            '[[project]]\nid = "design"\nfpga = "board"\ntop-symbol = "left"\n'
            'constraints = "board.xdc"\nsynthesis = "design.json"\n'
            'implementation = "design.fasm"\nbitstream = "design.bit"\n')
        self.source("src/left.v", ("left",), ("missing",))
        failure = self.cli("script")
        self.assertNotEqual(failure.returncode, 0)
        self.assertIn("unresolved import", failure.stderr)
        self.assertFalse((self.root / "build").exists())
        self.source("src/left.v", ("left",), ("leaf",))
        success = self.cli("script")
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertTrue((self.root / "build/fpga/board.toml").exists())


if __name__ == "__main__":
    unittest.main()
