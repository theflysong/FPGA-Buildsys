"""Shared HDL compiler options without source parsing."""

from dataclasses import replace
from pathlib import Path
import shlex
import tempfile
import unittest

from models import Fpga, HdlOptions, SynthesisProgram
from task.auxiliary import generate_auxiliary
from task.build import generate_script
from task.configure import configure
from task.model import build_model
from toolchains import select_toolchain
from util import ConfigError


class HdlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="buildsys-hdl-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        select_toolchain(self.root, "yosys")
        (self.root / "src").mkdir()
        (self.root / "include 中文").mkdir()
        (self.root / "src/top.v").write_text("module top; endmodule")
        self.config = self.root / "configuration.toml"
        self.config.write_text('name="HDL"\nid="hdl"\n[directories]\nsources=["src"]\n'
                               '[[simulation]]\nid="test"\ntop-symbol="top"\n')

    def test_hdl_configuration_validation_and_cleanup_scoping(self):
        original = self.config.read_text()
        for extra in ('[hdl]\ninclude-dirs=["../outside"]', '[hdl]\ninclude-dirs=["absent"]',
                      '[hdl]\ndefines={FLAG=1}', '[hdl]\ndefines={"bad-name"="1"}',
                      '[hdl]\ndefines={__VCD_FILE__="1"}', '[hdl]\ndefines=[]',
                      '[hdl]\ninclude-dirs="src"', '[hdl]\nunknown=true'):
            with self.subTest(extra=extra):
                self.config.write_text(original + extra, encoding="utf-8")
                with self.assertRaises(ConfigError):
                    configure(self.root, "model")
                self.assertEqual(configure(self.root, "clean", "test").hdl, HdlOptions())

    def test_explicit_preprocessing_options_reach_icarus_and_yosys(self):
        with self.config.open("a", encoding="utf-8") as stream:
            stream.write('[hdl]\ninclude-dirs=["include 中文"]\n'
                         'defines={ENABLED="1", TEXT=\'"a b $literal"\'}\n')
        (self.root / "src/header.vh").write_text("// header")
        project = build_model(configure(self.root, "build", "test"))
        generate_auxiliary(project)
        generate_script(project, project.simulations[0])
        script = (self.root / "build/jobs/test/build.sh").read_text(encoding="utf-8")
        arguments = shlex.split(next(line for line in script.splitlines() if line.startswith("iverilog ")))
        self.assertIn("-Iinclude 中文", arguments)
        self.assertIn('-DTEXT="a b $literal"', arguments)
        self.assertNotIn(".vh", project.filelist(project.simulations[0]).read_text())
        fpga = Fpga("board", "part", None, (), ())
        program = SynthesisProgram("design", fpga, "top", self.root / "build/design.json")
        generate_auxiliary(replace(project, toolchain="yosys", programs=(program,)))
        script = project.yosys_script(program).read_text(encoding="utf-8")
        self.assertIn('"-Iinclude 中文"', script)
        self.assertIn('"-DENABLED=1"', script)


if __name__ == "__main__":
    unittest.main()
