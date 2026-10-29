"""Check the read-only completion interface and its Bash adapter."""

from __future__ import annotations

import os
import json
import contextlib
import io
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BUILDSYS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDSYS_DIR))

import main as buildsys_entry
from task import install as installation_task


ENTRY = BUILDSYS_DIR / "main.py"
ADAPTER = BUILDSYS_DIR / "bash-completion/buildsys.bash"
BOOTSTRAP = Path("/usr/share/bash-completion/bash_completion")
BASH = str(Path("C:/Program Files/Git/bin/bash.exe")) if os.name == "nt" else shutil.which("bash")


class CompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        # Git Bash mounts the Windows temp directory as /tmp; relative paths
        # from that mount do not have the same parents as native Windows paths.
        temporary = tempfile.TemporaryDirectory(dir=BUILDSYS_DIR if os.name == "nt" else None)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project with spaces"
        self.auxiliary = self.root / "build/auxiliary"
        self.auxiliary.mkdir(parents=True)
        # No valid project is needed: only auxiliary file names are read.
        (self.root / "configuration.toml").write_text("invalid TOML [\n")
        for name in ("demo.f", "tb_other.f", "coreprog.ys", "project.map", "project.dep"):
            (self.auxiliary / name).write_text("exit 99\n")
        (self.auxiliary / "not_a_file.f").mkdir()
        (self.auxiliary / "invalid id.f").touch()
        if os.name == "nt":
            # Isolate wrappers from the checkout's Windows-only .venv, which
            # cannot be activated by Git Bash. Exercise real candidate logic.
            source = self.base / "source"
            source.mkdir()
            (source / "main.py").write_text(
                f"import runpy, sys\nsys.path.insert(0, {str(BUILDSYS_DIR)!r})\n"
                f"runpy.run_path({str(ENTRY)!r}, run_name='__main__')\n", encoding="utf-8")
            with patch.object(installation_task, "BUILDSYS_DIR", source), contextlib.redirect_stdout(io.StringIO()):
                installation_task.install_wrappers(self.root)
        else:
            installed = subprocess.run(
                [sys.executable, str(ENTRY), "install", str(self.root)],
                capture_output=True, text=True,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
        self.env = dict(os.environ)
        fake_tools = self.base / "tools"
        fake_tools.mkdir()
        for name in ("openFPGALoader", "yosys", "iverilog"):
            script = fake_tools / name
            script.write_text('#!/bin/sh\nprintf "called\\n" >> "$SIDE_EFFECT_LOG"\nexit 99\n')
            script.chmod(0o755)
        if os.name == "nt":
            # Git Bash needs an actual python3 launcher, not the Windows alias.
            (fake_tools / "python3").write_text(
                f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8")
        self.env["PATH"] = f"{fake_tools}{os.pathsep}{self.env['PATH']}"
        self.env["SIDE_EFFECT_LOG"] = str(self.base / "side-effects")

    def query(self, *words: str, wrapper: str = "buildsys") -> list[str]:
        if os.name == "nt" and wrapper == "buildsys":
            command = [str(self.root / "buildsys.bat")]
        elif os.name == "nt":
            if not BASH or not Path(BASH).is_file():
                self.skipTest("native Git Bash is unavailable")
            command = [BASH, (self.root / wrapper).as_posix()]
        else:
            command = [str(self.root / wrapper)]
        result = subprocess.run(
            [*command, "completion", "--", *words],
            cwd=self.base, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertFalse((self.base / "side-effects").exists())
        self.assertFalse((self.root / "jobs.sh").exists())
        self.assertFalse((self.root / "build/jobs").exists())
        return result.stdout.splitlines()

    def test_commands_and_missing_auxiliary(self) -> None:
        shutil.rmtree(self.auxiliary)
        self.assertEqual(set(self.query()), {
            "model", "auxiliary", "script", "build", "simulate", "synthesis", "implementation",
            "bitstream", "program", "xpr", "xpr-simulation", "xpr-synthesis", "xpr-implementation",
            "xpr-bitstream", "xpr-program", "clean", "cleandist", "init", "init-venv", "install", "completion",
            "toolchain",
        })
        self.assertEqual(self.query("sim"), ["simulate"])
        self.assertEqual(self.query("ini"), ["init", "init-venv"])
        self.assertEqual(self.query("init", ""), [])
        self.assertEqual(self.query("init-venv", ""), [])
        self.assertEqual(self.query("simulate", ""), [])
        self.assertEqual(self.query("clean", ""), [])
        self.assertFalse(self.auxiliary.exists())
        result = subprocess.run([sys.executable, str(ENTRY), "completion"],
                                cwd=self.base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("simulate", result.stdout.splitlines())

    def test_toolchain_names_without_selection_or_valid_configuration(self) -> None:
        self.assertEqual(self.query("toolchain", ""), ["yosys", "vivado"])
        self.assertEqual(self.query("toolchain", "v"), ["vivado"])
        self.assertEqual(self.query("toolchain", "yosys", ""), [])
        self.assertFalse((self.root / ".buildsys").exists())

    def test_context_ids_and_live_file_changes(self) -> None:
        for command in ("build", "simulate"):
            self.assertEqual(self.query(command, ""), ["demo", "tb_other"])
        for command in ("synthesis", "implementation", "bitstream", "program"):
            self.assertEqual(self.query(command, ""), ["coreprog"])
        self.assertEqual(self.query("xpr", ""), [])
        for command in ("clean", "cleandist"):
            self.assertEqual(set(self.query(command, "")), {"demo", "tb_other", "coreprog"})
        self.assertEqual(self.query("simulate", "tb"), ["tb_other"])
        self.assertEqual(self.query("simulate", "", wrapper="buildsys.sh"), ["demo", "tb_other"])
        self.assertEqual(self.query("simulate", "missing"), [])
        self.assertEqual(self.query("auxiliary", ""), [])
        self.assertEqual(self.query("build", "demo", ""), [])
        (self.auxiliary / "demo.f").unlink()
        (self.auxiliary / "new.f").touch()
        self.assertEqual(self.query("simulate", ""), ["new", "tb_other"])
        # Stale files with matching stems must not create duplicate clean candidates.
        (self.auxiliary / "new.ys").touch()
        self.assertEqual(self.query("clean", "").count("new"), 1)

    def test_first_ids_without_auxiliary_or_local_fpga_settings(self) -> None:
        shutil.rmtree(self.root / "build")
        (self.root / "configuration.toml").write_text(
            '[[simulation]]\nid = "tb_first"\n[[simulation]]\nid = "tb_second"\n'
            '[[simulation]]\nid = "tb_first"\n[[simulation]]\nid = "invalid id"\n'
            '[[project]]\nid = "first_program"\n'
            '[[xpr]]\nid = "first_export"\n'
        )
        self.assertEqual(self.query("simulate", "tb_f"), ["tb_first"])
        self.assertEqual(self.query("build", ""), ["tb_first", "tb_second"])
        self.assertEqual(self.query("synthesis", "first", wrapper="buildsys.sh"), ["first_program"])
        self.assertEqual(self.query("xpr", "first"), ["first_export"])
        self.assertEqual(set(self.query("cleandist", "")), {"tb_first", "tb_second", "first_program"})
        self.assertFalse((self.root / "build").exists())
        # Invalid private configuration has no bearing on completion.
        local = self.root / "build/fpga/ego1.toml"
        local.parent.mkdir(parents=True)
        local.write_text("invalid TOML [")
        self.assertEqual(self.query("program", ""), ["first_program"])
        self.assertEqual(local.read_text(), "invalid TOML [")
        self.assertFalse(self.auxiliary.exists())

    def test_auxiliary_and_configuration_ids_are_merged_for_each_target_type(self) -> None:
        (self.root / "configuration.toml").write_text(
            '[[simulation]]\nid = "configured_sim"\n[[project]]\nid = "configured_program"\n'
            '[[xpr]]\nid = "configured_export"\n'
        )
        self.assertEqual(self.query("simulate", ""), ["demo", "tb_other", "configured_sim"])
        self.assertEqual(self.query("simulate", "configured"), ["configured_sim"])
        self.assertEqual(self.query("program", ""), ["coreprog", "configured_program"])
        self.assertEqual(self.query("xpr", ""), ["configured_export"])
        (self.auxiliary / "coreprog.ys").unlink()
        (self.auxiliary / "invalid id.ys").touch()
        self.assertEqual(self.query("program", ""), ["configured_program"])
        self.assertEqual(set(self.query("clean", "")),
                         {"demo", "tb_other", "configured_sim", "configured_program"})
        (self.root / "configuration.toml").unlink()
        self.assertEqual(self.query("program", ""), [])
        self.assertEqual(self.query("simulate", ""), ["demo", "tb_other"])

    def test_program_options_and_no_device_access(self) -> None:
        self.assertEqual(self.query("program", "coreprog", "--p"), ["--protocol"])
        self.assertEqual(set(self.query("program", "coreprog", "")), {
            "--protocol", "--busdev-num", "--ftdi-serial",
        })
        self.assertEqual(self.query("program", "coreprog", "--protocol", ""), [])
        self.assertEqual(self.query("program", "coreprog", "--protocol", "ft2232", ""),
                         ["--busdev-num", "--ftdi-serial"])
        self.assertEqual(self.query("program", "coreprog", "--busdev-num", "1:2", ""),
                         ["--protocol"])
        self.assertEqual(self.query("program", "coreprog", "--ftdi-serial=SERIAL", ""),
                         ["--protocol"])
        self.assertEqual(self.query("program", "--protocol", "ft2232", ""), ["coreprog"])
        self.assertEqual(self.query("program", "coreprog", "--busdev-num", ""), [])

    def test_install_directory_candidates(self) -> None:
        (self.base / "destination with spaces").mkdir()
        (self.base / "destination-file").touch()
        self.assertEqual(self.query("install", "dest"), ["destination with spaces/"])
        self.assertEqual(self.query("install", "bui"), ["buildsys"])
        self.assertEqual(self.query("install", "comp"), ["completion"])
        for item in ("buildsys", "completion"):
            self.assertEqual(self.query("install", item, "dest"), ["destination with spaces/"])
        self.assertEqual(self.query("install", "unknown", "dest"), [])
        self.assertEqual(self.query("install", "completion", "destination", ""), ["--terminal"])

    def test_terminal_candidates(self) -> None:
        self.assertEqual(self.query("install", "completion", "--t"), ["--terminal"])
        self.assertEqual(self.query("install", "completion", "--terminal="),
                         ["--terminal=bash", "--terminal=powershell"])
        self.assertEqual(self.query("install", "completion", "--terminal=p"), ["--terminal=powershell"])
        self.assertEqual(self.query("install", "completion", "--terminal", ""), ["bash", "powershell"])
        self.assertEqual(self.query("install", "completion", "--terminal", "b"), ["bash"])
        (self.base / "destination").mkdir()
        self.assertEqual(self.query("install", "completion", "--terminal=powershell", "dest"), ["destination/"])
        self.assertEqual(self.query("install", "completion", "destination", "--terminal", "p"), ["powershell"])
        self.assertEqual(self.query("install", "completion", "destination", "--terminal=bash", ""), [])
        self.assertEqual(self.query("install", "buildsys", "--t"), [])

    def test_json_preserves_empty_and_unicode_words(self) -> None:
        (self.base / "中文 '目录").mkdir()
        for words, expected in ((["simulate", ""], ["demo", "tb_other"]),
                                (["install", "completion", "中文 '"], ["中文 '目录/"])):
            result = subprocess.run(
                [sys.executable, str(ENTRY), "--project", str(self.root), "completion", "--json"],
                input=json.dumps(words), cwd=self.base, env=self.env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), expected)
        for value in ('{', '{}', '[1]', '[null]'):
            result = subprocess.run([sys.executable, str(ENTRY), "completion", "--json"],
                                    input=value, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("completion JSON", result.stderr)

    def test_invalid_utf8_configuration_is_ignored(self) -> None:
        (self.root / "configuration.toml").write_bytes(b"\xff\xfe invalid TOML")
        self.assertEqual(self.query("simulate", ""), ["demo", "tb_other"])
        self.assertEqual(self.query("xpr-simulation", "missing", ""), [])

    def test_install_completion_to_custom_directory(self) -> None:
        destination = self.base / "completion destination"
        destination.mkdir()
        result = subprocess.run(
            [sys.executable, str(ENTRY), "install", "completion", destination.name, "--terminal=bash"],
            cwd=self.base, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(path.name for path in destination.iterdir()), {"buildsys", "buildsys.sh"})
        for name in ("buildsys", "buildsys.sh"):
            adapter = destination / name
            self.assertEqual(adapter.read_bytes(), ADAPTER.read_bytes())
            if os.name != "nt":
                self.assertEqual(adapter.stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.root / "jobs.sh").exists())
        missing = subprocess.run(
            [sys.executable, str(ENTRY), "install", "completion", str(destination / "absent"), "--terminal=bash"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("install directory does not exist", missing.stderr)
        unknown = subprocess.run(
            [sys.executable, str(ENTRY), "install", "unknown", str(destination)],
            capture_output=True, text=True,
        )
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("unknown install item", unknown.stderr)

    def test_install_default_destinations(self) -> None:
        with patch.object(installation_task, "install_completion") as installer:
            self.assertEqual(buildsys_entry.main(["install", "completion"]), 0)
            installer.assert_called_once_with(None, "powershell" if os.name == "nt" else "bash")
        for terminal in ("bash", "powershell"):
            for option in ([f"--terminal={terminal}"], ["--terminal", terminal]):
                with patch.object(installation_task, "install_completion") as installer:
                    self.assertEqual(buildsys_entry.main(["install", "completion", *option]), 0)
                    installer.assert_called_once_with(None, terminal)
        for args in (["install"], ["install", "buildsys"]):
            with patch.object(installation_task, "install_wrappers") as installer:
                self.assertEqual(buildsys_entry.main(args), 0)
                installer.assert_called_once_with(Path.cwd())

    def test_bash_adapter_without_bootstrap(self) -> None:
        if not BASH or not Path(BASH).is_file():
            self.skipTest("native Bash is unavailable")
        result = subprocess.run([
            BASH, "-c", '''set -eu
source "$1"
shift
COMP_WORDS=("$@")
COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))
_buildsys_complete
if (( ${#COMPREPLY[@]} )); then printf '%s\\n' "${COMPREPLY[@]}"; fi
''', "completion-test", ADAPTER.as_posix(), (self.root / "buildsys").as_posix(), "simulate", "tb",
        ], cwd=self.base, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["tb_other"])

    def test_bash_adapter_terminal_equals_and_split_words(self) -> None:
        if not BASH or not Path(BASH).is_file():
            self.skipTest("native Bash is unavailable")
        for words, expected in (
            (("install", "completion", "--terminal=p"), ["powershell"]),
            (("install", "completion", "--terminal", "=", "p"), ["powershell"]),
            (("install", "completion", "--terminal", "=", ""), ["bash", "powershell"]),
            (("install", "completion", "--terminal", "p"), ["powershell"]),
            (("install", "completion", "--terminal", "=", "bash", "dest"), ["destination/"]),
        ):
            (self.base / "destination").mkdir(exist_ok=True)
            result = subprocess.run([
                BASH, "-c", '''set -eu
source "$1"
shift
COMP_WORDS=("$@")
COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))
_buildsys_complete
if (( ${#COMPREPLY[@]} )); then printf '%s\\n' "${COMPREPLY[@]}"; fi
''', "completion-test", ADAPTER.as_posix(), (self.root / "buildsys").as_posix(), *words,
            ], cwd=self.base, env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), expected, words)

    @unittest.skipUnless(BOOTSTRAP.is_file(), "bash-completion is not installed")
    def test_lazy_loading_for_both_wrappers_and_paths(self) -> None:
        # Use a temporary completion directory rather than changing the system.
        shutil.rmtree(self.auxiliary)
        (self.root / "configuration.toml").write_text(
            '[[simulation]]\nid = "demo"\n[[simulation]]\nid = "tb_other"\n'
            '[[project]]\nid = "coreprog"\n'
        )
        data = self.base / "data"
        completions = data / "bash-completion/completions"
        completions.mkdir(parents=True)
        installed = subprocess.run(
            [sys.executable, str(ENTRY), "install", "completion", str(completions), "--terminal=bash"],
            capture_output=True, text=True,
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        env = dict(self.env, XDG_DATA_HOME=str(data))
        for wrapper in ("buildsys", "buildsys.sh"):
            for args, expected in (
                (["simulate", "tb"], ["tb_other"]),
                (["program", "coreprog", "--busdev-num", "1", ":", "2", ""], ["--protocol"]),
            ):
                command = str(self.root / wrapper)
                # Bash splits ':' in COMP_WORDS; the library must reassemble the USB address.
                line_args = ["program", "coreprog", "--busdev-num", "1:2", ""] if args[0] == "program" else args
                line = " ".join(shlex.quote(word) for word in [command, *line_args[:-1]]) + " " + line_args[-1]
                result = subprocess.run([
                    "bash", "-c", '''set -e
source "$1"
COMP_LINE=$2
COMP_POINT=${#COMP_LINE}
shift 2
COMP_WORDS=("$@")
COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))
__load_completion "${COMP_WORDS[0]}"
complete -p "${COMP_WORDS[0]}" >/dev/null
_buildsys_complete
if (( ${#COMPREPLY[@]} )); then printf '%s\\n' "${COMPREPLY[@]}"; fi
''', "completion-test", str(BOOTSTRAP), line, command, *args,
                ], cwd=self.base, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)
        self.assertFalse((self.base / "side-effects").exists())
        self.assertFalse(self.auxiliary.exists())
        self.assertFalse((self.root / "build/fpga").exists())


if __name__ == "__main__":
    unittest.main()
