"""PowerShell completion and profile installation, without touching real profiles."""

from __future__ import annotations

import base64
import codecs
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BUILDSYS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDSYS_DIR))

import main as entry
import powershell_completion as installation
from task.install import default_terminal, install_wrappers
from util import ConfigError


SHELLS = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
ADAPTER = BUILDSYS_DIR / "powershell-completion/buildsys.ps1"


def ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def powershell(shell: str, script: str, **kwargs) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(("$ProgressPreference = 'SilentlyContinue'\n" + script).encode("utf-16le")).decode("ascii")
    return subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          capture_output=True, encoding="utf-8-sig", **kwargs)


class ProfileInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=BUILDSYS_DIR if os.name == "nt" else None)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profiles = [self.root / name / "profile.ps1" for name in ("WindowsPowerShell", "PowerShell")]
        self.mock_profiles = patch.object(installation, "discover_profiles", return_value=self.profiles).start()
        self.addCleanup(patch.stopall)

    def install(self, directory=None):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            installation.install(directory)
        return output.getvalue()

    def test_default_install_and_reinstall_are_idempotent(self):
        output = self.install()
        initial = [profile.read_bytes() for profile in self.profiles]
        self.install()
        for profile, content in zip(self.profiles, initial):
            self.assertEqual(profile.read_bytes(), content)
            self.assertTrue(content.startswith(codecs.BOM_UTF8))
            script = profile.parent / "completions/buildsys.ps1"
            self.assertTrue(script.read_bytes().startswith(codecs.BOM_UTF8))
            self.assertIn(str(script), output)
            self.assertIn(str(script), content.decode("utf-8-sig"))

    def test_custom_destination_updates_block_and_preserves_encoding_and_user_content(self):
        custom = self.root / "中文 completion's directory"
        custom.mkdir()
        for profile, encoding in zip(self.profiles, ("utf-8-sig", "utf-16")):
            profile.parent.mkdir()
            profile.write_bytes("# 用户配置\r\n$example = 'unchanged'".encode(encoding))
        self.install()
        for profile in self.profiles:
            with profile.open("ab") as stream:
                encoding = "utf-16-le" if profile == self.profiles[1] else "utf-8"
                stream.write("# trailing user content\r\n".encode(encoding))
        self.install(custom)
        for profile, encoding in zip(self.profiles, ("utf-8-sig", "utf-16")):
            content = profile.read_bytes().decode(encoding)
            self.assertTrue(content.startswith("# 用户配置\r\n$example = 'unchanged'\r\n"))
            self.assertTrue(content.endswith("# trailing user content\r\n"))
            self.assertEqual(content.count(installation.START_MARKER), 1)
            self.assertIn("completion''s directory", content)
            self.assertNotIn("completions/buildsys.ps1", content)
        self.assertTrue((custom / "buildsys.ps1").is_file())

    def test_bomless_and_legacy_profiles(self):
        profile = self.profiles[0]
        profile.parent.mkdir()
        for encoding, text in (("utf-8", "# 用户配置\n"), ("cp1252", "# café\r\n")):
            original = text.encode(encoding)
            profile.write_bytes(original)
            with patch.object(installation.locale, "getpreferredencoding", return_value=encoding):
                result = installation.profile_content(profile, self.root / "中文/buildsys.ps1")
            self.assertTrue(result.startswith(original))
            self.assertEqual(result.decode(encoding).count(installation.START_MARKER), 1)
            self.assertIn(b"FromBase64String", result)

    def test_missing_directory_and_missing_shell_do_not_write_profiles(self):
        with self.assertRaisesRegex(ConfigError, "install directory does not exist"):
            self.install(self.root / "absent")
        self.mock_profiles.side_effect = ConfigError("PowerShell was not found")
        with self.assertRaisesRegex(ConfigError, "PowerShell was not found"):
            self.install()
        self.assertFalse(any(profile.exists() for profile in self.profiles))
        with patch.object(installation.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ConfigError, "PowerShell was not found"):
                REAL_DISCOVER_PROFILES()

    def test_malformed_profile_encoding_leaves_all_profiles_untouched(self):
        self.profiles[1].parent.mkdir()
        original = codecs.BOM_UTF16_LE + b"\x00"
        self.profiles[1].write_bytes(original)
        with self.assertRaisesRegex(ConfigError, "could not preserve profile encoding"):
            self.install()
        self.assertEqual(self.profiles[1].read_bytes(), original)
        self.assertFalse(self.profiles[0].exists())
        self.assertFalse((self.profiles[0].parent / "completions").exists())

    def test_cli_defaults_and_validation(self):
        for platform, terminal in (("nt", "powershell"), ("posix", "bash")):
            with patch("task.install.os.name", platform):
                self.assertEqual(default_terminal(), terminal)
        for args in (["install", "--terminal=bash"], ["install", "buildsys", "--terminal=powershell"],
                     ["install", "completion", "--terminal=zsh"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                entry.main(args)
            self.assertEqual(error.exception.code, 2)


REAL_DISCOVER_PROFILES = installation.discover_profiles


@unittest.skipUnless(SHELLS, "PowerShell is unavailable")
class PowerShellAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=BUILDSYS_DIR if os.name == "nt" else None)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "中文 project's directory"
        self.project.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            install_wrappers(self.project)
        (self.project / "configuration.toml").write_text(
            '[[simulation]]\nid="tb_one"\n[[simulation]]\nid="tb_two"\n'
            '[[project]]\nid="core"\n', encoding="utf-8")
        (self.root / "目标 '目录").mkdir()

    def complete(self, shell, lines, cursors=None, adapter=ADAPTER):
        request = json.dumps([{"line": line, "cursor": cursor}
                              for line, cursor in zip(lines, cursors or map(len, lines))])
        script = f". {ps_literal(adapter)}\n" + r'''
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$requests = ConvertFrom-Json -InputObject REQUEST
foreach ($request in $requests) {
    $result = [System.Management.Automation.CommandCompletion]::CompleteInput([string]$request.line, [int]$request.cursor, $null)
    ConvertTo-Json -InputObject @($result.CompletionMatches | ForEach-Object CompletionText) -Compress
}
'''.replace("REQUEST", ps_literal(request))
        result = powershell(shell, script, cwd=self.root, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_commands_targets_options_and_quoted_directories(self):
        wrapper = self.project / ("buildsys.bat" if os.name == "nt" else "buildsys")
        command = "& " + ps_literal(wrapper)
        cases = [
            (" sim", ["simulate"]),
            (" simulate ", ["tb_one", "tb_two"]),
            (" simulate tb_t", ["tb_two"]),
            (" xpr-simulation ", ["tb_one", "tb_two"]),
            (" toolchain ", ["yosys", "vivado"]),
            (" install completion --terminal=p", ["--terminal=powershell"]),
            (" install completion --terminal ", ["bash", "powershell"]),
            (" install completion '目标 '", ["'目标 ''目录/'"]),
            (" program core --busdev-num 1:2 ", ["--protocol"]),
            (" xpr-program core --device 1 ", ["--hw-server"]),
        ]
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.complete(shell, [command + suffix for suffix, _ in cases])
                self.assertEqual(result, [expected for _, expected in cases])
        self.assertFalse((self.project / "build").exists())
        self.assertFalse((self.project / ".buildsys").exists())

    def test_cursor_and_all_wrapper_names(self):
        for shell in SHELLS:
            wrappers = ["buildsys", "buildsys.sh"]
            if os.name == "nt":
                wrappers.append("buildsys.bat")
            for wrapper in wrappers:
                with self.subTest(shell=shell, wrapper=wrapper):
                    command = "& " + ps_literal(self.project / wrapper)
                    line = command + " simulate tb_two ignored"
                    cursor = len(command + " simulate tb_t")
                    self.assertEqual(self.complete(shell, [line], [cursor]), [["tb_two"]])

    def test_loader_from_installed_profile(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                profile = self.root / "profile.ps1"
                with patch.object(installation, "discover_profiles", return_value=[profile]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    installation.install(None)
                wrapper = self.project / ("buildsys.bat" if os.name == "nt" else "buildsys")
                self.assertEqual(self.complete(shell, ["& " + ps_literal(wrapper) + " sim"], adapter=profile), [["simulate"]])

    @unittest.skipUnless(os.name == "nt", "Windows console isolation regression")
    def test_query_preserves_parent_console_and_uses_powershell_location(self):
        source = self.root / "probe source"
        source.mkdir()
        probe = self.root / "console-state.json"
        (source / "main.py").write_text(
            "import ctypes, json, os, runpy, sys\nfrom pathlib import Path\n"
            f"Path({str(probe)!r}).write_text(json.dumps({{\n"
            "    'input_cp': ctypes.windll.kernel32.GetConsoleCP(),\n"
            "    'output_cp': ctypes.windll.kernel32.GetConsoleOutputCP(),\n"
            "    'cwd': os.getcwd(),\n"
            "}))\n"
            # Simulate activation changing console code pages. A detached
            # child may allocate its own console, but must not alter its parent.
            "ctypes.windll.kernel32.SetConsoleCP(437)\n"
            "ctypes.windll.kernel32.SetConsoleOutputCP(437)\n"
            # Enough stderr to fill a pipe: completion must drain both streams.
            "sys.stderr.write('test diagnostic\\n' * 10000)\n"
            f"sys.path.insert(0, {str(BUILDSYS_DIR)!r})\n"
            f"runpy.run_path({str(BUILDSYS_DIR / 'main.py')!r}, run_name='__main__')\n",
            encoding="utf-8")
        with patch("task.install.BUILDSYS_DIR", source), contextlib.redirect_stdout(io.StringIO()):
            install_wrappers(self.project)
        line = "& " + ps_literal(self.project / "buildsys.bat") + " install completion '目标 '"
        script = f". {ps_literal(ADAPTER)}\nSet-Location -LiteralPath {ps_literal(self.root)}\n" + r'''
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class BuildsysConsole {
    [DllImport("kernel32.dll")] public static extern uint GetConsoleCP();
    [DllImport("kernel32.dll")] public static extern uint GetConsoleOutputCP();
}
'@
$beforeInput = [BuildsysConsole]::GetConsoleCP()
$beforeOutput = [BuildsysConsole]::GetConsoleOutputCP()
$global:LASTEXITCODE = 37
$line = LINE
$result = [System.Management.Automation.CommandCompletion]::CompleteInput($line, $line.Length, $null)
ConvertTo-Json -Compress -InputObject @{
    Candidates = @($result.CompletionMatches | ForEach-Object CompletionText)
    ExitCode = $global:LASTEXITCODE
    BeforeInputCP = $beforeInput
    BeforeOutputCP = $beforeOutput
    AfterInputCP = [BuildsysConsole]::GetConsoleCP()
    AfterOutputCP = [BuildsysConsole]::GetConsoleOutputCP()
}
'''.replace("LINE", ps_literal(line))
        # A private hidden console gives the parent a real console to inherit;
        # the original native pipeline incorrectly passed it to completion.
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = powershell(shell, script, cwd=BUILDSYS_DIR, timeout=60,
                                    startupinfo=startup, creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                parent = json.loads(result.stdout)
                self.assertEqual(parent["Candidates"], ["'目标 ''目录/'"])
                self.assertEqual(parent["ExitCode"], 37)
                self.assertGreater(parent["BeforeInputCP"], 0)
                self.assertGreater(parent["BeforeOutputCP"], 0)
                self.assertEqual(parent["BeforeInputCP"], parent["AfterInputCP"])
                self.assertEqual(parent["BeforeOutputCP"], parent["AfterOutputCP"])
                state = json.loads(probe.read_text())
                self.assertEqual(Path(state["cwd"]), self.root)

    def test_real_profile_discovery_is_read_only(self):
        profiles = REAL_DISCOVER_PROFILES()
        self.assertTrue(profiles)
        self.assertTrue(all(profile.is_absolute() and profile.name == "profile.ps1" for profile in profiles))


if __name__ == "__main__":
    unittest.main()
