"""Check project initialization and the template's simulation timing."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1] / "main.py"


class InitTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project with spaces"
        self.root.mkdir()
        result = self.run_command(sys.executable, str(ENTRY), "install", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_command(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=cwd or self.base, capture_output=True,
                              text=True, timeout=15)

    def snapshot(self) -> dict[str, bytes | None]:
        return {path.relative_to(self.root).as_posix(): path.read_bytes() if path.is_file() else None
                for path in self.root.rglob("*")}

    def test_wrapper_init_from_another_directory_and_repeat(self) -> None:
        wrappers = {name: ((self.root / name).read_bytes(), (self.root / name).stat().st_mode)
                    for name in ("buildsys", "buildsys.sh")}
        result = self.run_command(str(self.root / "buildsys"), "init")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / "configuration.toml").exists())
        for name, (content, mode) in wrappers.items():
            self.assertEqual((self.root / name).read_bytes(), content)
            self.assertEqual((self.root / name).stat().st_mode, mode)
        # Configuring the new project checks metadata and source dependency resolution.
        configured = self.run_command(str(self.root / "buildsys"), "aux")
        self.assertEqual(configured.returncode, 0, configured.stderr)
        self.assertIn("sim/tbSimulation.v", (self.root / "build/aux/example_simulation.f").read_text())
        before = self.snapshot()
        repeated = self.run_command(str(self.root / "buildsys"), "init")
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("containing only buildsys and buildsys.sh", repeated.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_python_init_defaults_to_current_directory(self) -> None:
        result = self.run_command(sys.executable, str(ENTRY), "init", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "configuration.toml").is_file())

    def test_init_rejects_extra_content_without_changes(self) -> None:
        for name in ("notes.txt", ".hidden", "src"):
            with self.subTest(name=name):
                extra = self.root / name
                if name == "src":
                    extra.mkdir()
                else:
                    extra.write_text("user content\n")
                before = self.snapshot()
                result = self.run_command(str(self.root / "buildsys"), "init")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("containing only buildsys and buildsys.sh", result.stderr)
                self.assertEqual(self.snapshot(), before)
                if extra.is_dir():
                    extra.rmdir()
                else:
                    extra.unlink()

    def test_init_rejects_missing_or_invalid_wrappers(self) -> None:
        launcher = self.root / "buildsys"
        launcher.unlink()
        for invalid_directory in (False, True):
            with self.subTest(invalid_directory=invalid_directory):
                if invalid_directory:
                    launcher.mkdir()
                before = self.snapshot()
                result = self.run_command(sys.executable, str(ENTRY), "--project", str(self.root), "init")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("containing only buildsys and buildsys.sh", result.stderr)
                self.assertEqual(self.snapshot(), before)
        missing = self.run_command(sys.executable, str(ENTRY), "--project", str(self.base / "missing"), "init")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("project directory does not exist", missing.stderr)

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog unavailable")
    def test_template_simulation_reads_a_character_every_500_ms(self) -> None:
        initialized = self.run_command(str(self.root / "buildsys.sh"), "init")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        result = self.run_command(str(self.root / "buildsys"), "simulate", "example_simulation")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = re.findall(r"(\d+) ms: addr=(\d+) data=0x([0-9a-fA-F]+) \((.)\)", result.stdout)
        self.assertEqual([(int(time), int(addr), int(data, 16), char)
                          for time, addr, data, char in records],
                         [(index * 500, index, ord(char), char)
                          for index, char in enumerate("Hello,World!")])
        waveform = (self.root / "build/sim/example.vcd").read_text()
        self.assertRegex(waveform, r"\$timescale\s+1ps\s+\$end")
        address_declaration = re.search(
            r"\$var\s+reg\s+4\s+(\S+)\s+addr(?:\s+\[3:0\])?\s+\$end", waveform
        )
        self.assertIsNotNone(address_declaration)
        address_symbol = address_declaration.group(1)
        time = 0
        addresses = []
        for line in waveform.splitlines():
            if line.startswith("#"):
                time = int(line[1:])
            elif line.startswith("b"):
                value, symbol = line[1:].split()
                if symbol == address_symbol:
                    addresses.append((time, int(value, 2)))
        self.assertEqual(addresses, [(index * 500_000_000_000, index) for index in range(12)])
        self.assertEqual(time, 6_000_000_000_000)


if __name__ == "__main__":
    unittest.main()
