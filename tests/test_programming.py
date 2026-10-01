"""Programming behavior with a simulated USB loader; never writes to hardware."""
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
HEADER = "Bus device vid:pid       probe type      manufacturer serial               product"


class ProgrammingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="buildsys programming ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "constraints").mkdir()
        (self.root / "constraints/board.xdc").write_text("# constraints\n")
        (self.root / "src/top.v").write_text("module top; endmodule\n")
        (self.root / "src/top.toml").write_text('[[module.export]]\nname = "top"\n')
        (self.root / "configuration.toml").write_text(
            'name = "Programming test"\nid = "example"\n'
            '[directories]\nsources = ["src"]\nconstraints = ["constraints"]\n'
            'synthesis = "build/synth"\nimplementation = "build/impl"\n'
            'bitstream = "build/bits"\n'
            '[[fpga]]\nid = "ego1"\npart = "xc7a35tcsg324-1"\n'
            '[[program]]\nid = "coreprog"\nfpga = "ego1"\ntop-symbol = "top"\n'
            'synthesis = "core.json"\nimplementation = "core.fasm"\n'
            'bitstream = "core image.bit"\nconstraints = "board.xdc"\n'
        )
        self.tool_dir = self.root / "tools"
        self.tool_dir.mkdir()
        loader = self.tool_dir / "openFPGALoader"
        loader.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args == ["--scan-usb"]:
    print(Path(os.environ["SCAN_FILE"]).read_text(), end="")
    sys.exit(int(os.environ.get("SCAN_EXIT", "0")))
if args == ["--list-cables"]:
    print("empty\\ncable name               vid:pid\\nft2232                  0x0403:6010\\nft2232_b                0x0403:6010\\njlink                   0x1366:0105")
    sys.exit(int(os.environ.get("LIST_EXIT", "0")))
if "--detect" in args:
    print("Detected xc7a35")
    sys.exit(int(os.environ.get("DETECT_EXIT", "0")))
if "-m" in args:
    print("SRAM programming complete")
    sys.exit(int(os.environ.get("PROGRAM_EXIT", "0")))
sys.exit(3)
''')
        loader.chmod(0o755)
        self.env = dict(os.environ)
        self.env.update(PATH=f"{self.tool_dir}:{self.env['PATH']}",
                        CALL_LOG=str(self.root / "calls.jsonl"), SCAN_FILE=str(self.root / "scan.txt"))
        self.scan([(1, 2, "0403:6010", "SERIAL_A", "ft2232")])
        generated = self.cli("script")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.bitstream = self.root / "build/bits/core image.bit"
        self.bitstream.parent.mkdir(parents=True)
        self.bitstream.write_bytes(b"test bitstream")

    def scan(self, devices: list[tuple[int, int, str, str, str]]) -> None:
        lines = ["empty", f"found {len(devices)} USB device", HEADER]
        positions = [0, HEADER.index("device"), HEADER.index("vid:pid"), HEADER.index("probe type"),
                     HEADER.index("manufacturer"), HEADER.index("serial"), HEADER.index("product")]
        for bus, device, vidpid, serial, probe in devices:
            values = [str(bus), str(device), vidpid, probe, "FTDI Device", serial, "USB adapter"]
            row = ""
            for position, value in zip(positions, values):
                row = row.ljust(position) + value
            lines.append(row)
        (self.root / "scan.txt").write_text("\n".join(lines) + "\n")
        (self.root / "calls.jsonl").write_text("")

    def run_command(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(args, env=self.env, capture_output=True, text=True)
        for line in result.stderr.splitlines():
            if line.startswith("Programming log: "):
                log = Path(line.split(": ", 1)[1])
                self.assertEqual(log.parents[1], Path("/dev/shm"))
                self.assertTrue(log.is_file())
                self.addCleanup(shutil.rmtree, log.parent)
        return result

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_command([sys.executable, str(ENTRY), "--project", str(self.root), *args])

    def dispatch(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_command([str(self.root / "jobs.sh"), *args])

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def test_protocol_is_required_in_both_entries(self) -> None:
        for result in (self.cli("program", "coreprog"), self.dispatch("program", "coreprog")):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--protocol", result.stderr)
        self.assertEqual(self.calls(), [])
        both = self.cli("program", "coreprog", "--protocol", "ft2232",
                        "--busdev-num", "1:2", "--ftdi-serial", "SERIAL_A")
        self.assertNotEqual(both.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_unique_device_uses_existing_bitstream_without_synthesis(self) -> None:
        auxiliary = self.root / "build/aux/coreprog.ys"
        before = auxiliary.stat().st_mtime_ns
        result = self.cli("program", "coreprog", "--protocol", "ft2232")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[:3],
                         ["configure", "script generation", "script execution"])
        self.assertEqual(auxiliary.stat().st_mtime_ns, before)
        base = ["-c", "ft2232", "--busdev-num", "1:2"]
        self.assertEqual(self.calls(), [["--scan-usb"], ["--list-cables"],
                                       [*base, "--detect"], [*base, "-m", "build/bits/core image.bit"]])
        for path in (self.root / "build/jobs").rglob("*.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", str(path)]).returncode, 0)

    def test_multiple_devices_require_a_unique_selector(self) -> None:
        devices = [(1, 2, "0403:6010", "SERIAL_A", "ft2232"),
                   (1, 3, "0403:6010", "SERIAL_B", "ft2232")]
        self.scan(devices)
        ambiguous = self.dispatch("program", "coreprog", "--protocol", "ft2232")
        self.assertNotEqual(ambiguous.returncode, 0)
        self.assertIn("multiple devices", ambiguous.stderr)
        self.assertIn("SERIAL_A", ambiguous.stderr)
        self.assertIn("SERIAL_B", ambiguous.stderr)
        self.assertEqual(len(self.calls()), 2)
        for option, value in (("--busdev-num", "001:003"), ("--ftdi-serial", "SERIAL_B")):
            with self.subTest(option=option):
                self.scan(devices)
                selected = self.dispatch("program", "coreprog", "--protocol", "ft2232", option, value)
                self.assertEqual(selected.returncode, 0, selected.stderr)
                for call in self.calls()[2:]:
                    self.assertEqual(call[call.index("--busdev-num") + 1], "1:3")
                    if option == "--ftdi-serial":
                        self.assertEqual(call[call.index(option) + 1], value)
        self.scan([(1, 2, "0403:6010", "DUPLICATE", "ft2232"),
                   (1, 3, "0403:6010", "DUPLICATE", "ft2232")])
        duplicate = self.dispatch("program", "coreprog", "--protocol", "ft2232",
                                  "--ftdi-serial", "DUPLICATE")
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(len(self.calls()), 2)

    def test_unknown_protocol_empty_scan_and_selector_mismatch(self) -> None:
        scenarios = [([], "ft2232", (), "No USB device"),
                     ([(1, 2, "0403:6010", "SERIAL_A", "ft2232")], "unknown", (), "Unknown"),
                     ([(1, 2, "0403:6010", "SERIAL_A", "ft2232")], "jlink", (), "No USB device"),
                     ([(1, 2, "0403:6010", "SERIAL_A", "ft2232")], "ft2232", ("--busdev-num", "1:9"), "matches no device"),
                     ([(1, 2, "0403:6010", "SERIAL_A", "ft2232")], "ft2232", ("--ftdi-serial", "MISSING"), "matches no device")]
        for devices, protocol, selector, error in scenarios:
            with self.subTest(error=error, selector=selector):
                self.scan(devices)
                result = self.dispatch("program", "coreprog", "--protocol", protocol, *selector)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertEqual(self.calls(), [["--scan-usb"], ["--list-cables"]])

    def test_duplicate_aliases_do_not_make_one_device_ambiguous(self) -> None:
        self.scan([(1, 2, "0403:6010", "SERIAL_A", "ft2232"),
                   (1, 2, "0403:6010", "SERIAL_A", "digilent")])
        result = self.dispatch("program", "coreprog", "--protocol", "ft2232")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 4)

    def test_scan_and_detect_failures_prevent_programming(self) -> None:
        for environment, expected_calls in (("SCAN_EXIT", 1), ("LIST_EXIT", 2), ("DETECT_EXIT", 3)):
            with self.subTest(environment=environment):
                self.scan([(1, 2, "0403:6010", "SERIAL_A", "ft2232")])
                self.env[environment] = "1"
                result = self.dispatch("program", "coreprog", "--protocol", "ft2232")
                del self.env[environment]
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(self.calls()), expected_calls)
                self.assertTrue(all("-m" not in call for call in self.calls()))
        self.scan([(1, 2, "0403:6010", "SERIAL_A", "ft2232")])
        self.env["PROGRAM_EXIT"] = "1"
        result = self.dispatch("program", "coreprog", "--protocol", "ft2232")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 4)

    def test_missing_bitstream_and_unrecognized_scan_format_stop_before_detection(self) -> None:
        self.bitstream.unlink()
        result = self.dispatch("program", "coreprog", "--protocol", "ft2232")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing or empty bitstream", result.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.bitstream.write_bytes(b"bitstream")
        (self.root / "calls.jsonl").write_text("")
        (self.root / "scan.txt").write_text("unrecognized format\n")
        result = self.dispatch("program", "coreprog", "--protocol", "ft2232")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot parse", result.stderr)
        self.assertEqual(len(self.calls()), 2)
