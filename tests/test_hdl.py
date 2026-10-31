"""Automatic HDL dependencies and shared preprocessing across backends."""

from dataclasses import replace
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from hdl import parse_source
from models import Fpga, HdlOptions, SourceModel, SourceSymbols, SynthesisProgram
from task.auxiliary import generate_auxiliary
from task.build import generate_script
from task.configure import configure
from task.model import build_model, generate_model, source_filename
from util import ConfigError, source_closure


class HdlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hdl 中文 '[$] ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "src").mkdir()
        (self.root / "include 中文").mkdir()
        self.config = self.root / "configuration.toml"
        self.config.write_text('name="HDL"\nid="hdl"\n[directories]\nsources=["src"]\n'
                               '[[simulation]]\nid="test"\ntop-symbol="top"\n', encoding="utf-8")

    def write(self, path, content):
        target = self.root / path
        target.write_text(content, encoding="utf-8")
        return target

    def test_mixed_sources_parameters_arrays_generate_and_gate_primitives(self):
        self.write("src/leaf.v", 'module leaf #(parameter N=1); endmodule\nmodule alternate; endmodule')
        self.write("src/top.sv", '''module top;
            leaf #(.N(2)) a(), b[2]();
            if (0) begin : conditional alternate c(); end
            wire x; and g(x, 1'b1, 1'b0);
            initial $display("module fake; missing inst(); endmodule");
            // module ignored; imaginary inst(); endmodule
            endmodule''')
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources["src/top.sv"].symbols.imports, ("alternate", "leaf"))
        self.assertEqual(source_closure(project, "top"), ["src/leaf.v", "src/top.sv"])

    def test_packages_interfaces_modports_and_local_scopes(self):
        self.write("src/types.sv", 'package types; typedef logic [7:0] word; endpackage')
        self.write("src/bus.sv", 'interface bus; logic valid; modport device(input valid); endinterface')
        self.write("src/device.sv", '''module device(bus.device port);
            import types::*; types::word value;
            class local_class; static int count; endclass
            initial local_class::count = 1;
            endmodule''')
        self.write("src/top.v", 'module top; bus b(); device d(b); endmodule')
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources["src/device.sv"].symbols.imports, ("bus", "types"))
        self.assertEqual(set(project.sources["src/device.sv"].dependencies),
                         {"src/bus.sv", "src/types.sv"})
        self.assertEqual(source_closure(project, "top")[-1], "src/top.v")

    def test_plain_interface_ports_and_package_qualified_types(self):
        self.write("src/types.sv", 'package types; typedef logic [7:0] word; endpackage')
        self.write("src/bus.sv", 'interface bus; logic valid; endinterface')
        self.write("src/top.sv", 'module top(bus port); types::word value; endmodule')
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources["src/top.sv"].symbols.imports, ("bus", "types"))
        self.assertEqual(source_closure(project, "top"), ["src/bus.sv", "src/types.sv", "src/top.sv"])

    def test_nested_includes_macros_and_stale_metadata(self):
        self.write("include 中文/inner.svh", '`define LEAF leaf\n')
        self.write("include 中文/outer.vh", '`include "inner.svh"\n')
        self.write("src/leaf.v", 'module leaf; endmodule')
        self.write("src/top.sv", '''`include "outer.vh"
            module top;
            `ifdef ENABLED
                `LEAF selected();
            `else
                missing disabled();
            `endif
            endmodule''')
        self.write("src/top.toml", 'broken metadata intentionally ignored [')
        with self.config.open("a", encoding="utf-8") as stream:
            stream.write('\n[hdl]\ninclude-dirs=["include 中文"]\ndefines={ENABLED="1"}\n')
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources["src/top.sv"].symbols.imports, ("leaf",))
        self.assertEqual(project.sources["src/top.sv"].includes,
                         ("include 中文/inner.svh", "include 中文/outer.vh"))
        self.assertEqual(set(project.sources), {"src/leaf.v", "src/top.sv"})
        generate_model(project)
        record = json.loads((project.model_dir / source_filename("src/top.sv")).read_text(encoding="utf-8"))
        self.assertEqual(record["includes"], list(project.sources["src/top.sv"].includes))

    def test_relative_include_and_macros_do_not_leak_between_files(self):
        self.write("src/local.svh", '`define LOCAL 1\n')
        self.write("src/a.v", '`include "local.svh"\nmodule a; endmodule')
        self.write("src/top.sv", '`ifdef LOCAL\n invalid syntax [\n`endif\nmodule top; endmodule')
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources["src/a.v"].includes, ("src/local.svh",))
        self.assertEqual(project.sources["src/top.sv"].includes, ())

    def test_included_syntax_errors_have_unicode_source_locations(self):
        header = self.write("include 中文/parameters.svh", '`define WIDTH 8\n')
        self.write("src/top.sv", '`include "parameters.svh"\nmodule top; logic [`WIDTH-1:0] data; endmodule')
        with self.config.open("a", encoding="utf-8") as stream:
            stream.write('[hdl]\ninclude-dirs=["include 中文"]\n')
        project = build_model(configure(self.root, "model"))
        self.assertEqual(project.sources["src/top.sv"].includes, ("include 中文/parameters.svh",))
        header.write_text('module invalid( ; endmodule', encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, r"include 中文[\\/]parameters\.svh:\d+:\d+"):
            build_model(configure(self.root, "model"))

    def test_missing_include_and_syntax_errors_have_source_locations(self):
        for text in ('`include "absent.svh"\nmodule top; endmodule', 'module top( ; endmodule'):
            self.write("src/top.sv", text)
            with self.subTest(text=text), self.assertRaisesRegex(ConfigError, r"top\.sv:\d+:\d+"):
                build_model(configure(self.root, "model"))
            self.assertFalse((self.root / "build").exists())

    def test_duplicate_definitions_in_one_file_are_rejected(self):
        self.write("src/top.v", 'module top; endmodule module top; endmodule')
        with self.assertRaisesRegex(ConfigError, "duplicate export"):
            build_model(configure(self.root, "model"))

    def test_missing_parser_is_actionable_and_configuration_stays_lazy(self):
        source = self.write("src/top.v", 'module top; endmodule')
        with patch.dict("sys.modules", {"pyslang": None}):
            project = configure(self.root, "model")
            self.assertEqual(project.sources, {})
            with self.assertRaisesRegex(ConfigError, "init-venv"):
                parse_source(self.root, source, HdlOptions())

    def test_hdl_configuration_validation_and_cleanup_scoping(self):
        self.write("src/top.v", 'module top; endmodule')
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
        self.write("src/top.v", 'module top; endmodule')
        with self.config.open("a", encoding="utf-8") as stream:
            stream.write('[hdl]\ninclude-dirs=["include 中文"]\n'
                         'defines={ENABLED="1", TEXT=\'"a b $literal"\'}\n')
        project = replace(configure(self.root, "build", "test"), exports={"top": "src/top.v"},
                          sources={"src/top.v": SourceModel(SourceSymbols((), ("top",)), (), ())})
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
