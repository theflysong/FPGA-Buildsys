"""Wrapper forwarding, exit status and virtual environment activation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import venv

from task.install import install_wrappers


BUILDSYS_DIR = Path(__file__).resolve().parents[1]
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")


class ShellWrapperTests(unittest.TestCase):
    @unittest.skipUnless(BASH and Path(BASH).is_file(), "Requires native Bash")
    def test_only_activates_when_buildsys_environment_is_not_active(self) -> None:
        with tempfile.TemporaryDirectory(dir=BUILDSYS_DIR if os.name == "nt" else None) as temporary:
            base = Path(temporary)
            source = base / "buildsys source"
            source.mkdir()
            (source / "main.py").touch()
            project = base / "project with spaces"
            project.mkdir()
            shell_project = project.as_posix()
            if os.name == "nt":
                shell_project = "/" + project.drive[0].lower() + shell_project[2:]
            scripts = source / ".venv/bin"
            scripts.mkdir(parents=True)
            virtualenv = scripts.parent
            activation_log = base / "activations"
            (scripts / "activate").write_text(
                f'printf "activated\\n" >> {shlex.quote(activation_log.as_posix())}\n'
                f'export VIRTUAL_ENV={shlex.quote(virtualenv.as_posix())}\n',
                encoding="utf-8", newline="\n",
            )
            python = scripts / "python"
            python.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\nexit 7\n',
                encoding="utf-8", newline="\n",
            )
            python.chmod(0o755)
            with patch("task.install.BUILDSYS_DIR", source):
                install_wrappers(project)
            for wrapper in ("buildsys", "buildsys.sh"):
                for active in (None, "", str(base / "another .venv"), virtualenv.as_posix(),
                               virtualenv.as_posix() + "/", virtualenv.as_posix() + "/."):
                    with self.subTest(wrapper=wrapper, active=active):
                        activation_log.unlink(missing_ok=True)
                        env = dict(os.environ)
                        env.pop("VIRTUAL_ENV", None)
                        if active is not None:
                            env["VIRTUAL_ENV"] = active
                        result = subprocess.run(
                            [BASH, (project / wrapper).as_posix(), "first", "two words", "a&b"],
                            cwd=base, env=env, capture_output=True, text=True, timeout=20,
                        )
                        self.assertEqual(result.returncode, 7, result.stderr)
                        self.assertEqual(result.stdout.splitlines()[1:],
                                         ["--project", shell_project, "first", "two words", "a&b"])
                        expected_activation = active in (None, "", str(base / "another .venv"))
                        self.assertEqual(activation_log.exists(), expected_activation)
                        if expected_activation:
                            self.assertEqual(activation_log.read_text(), "activated\n")


class BatchWrapperTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Requires Windows cmd.exe")
    def test_only_activates_when_buildsys_environment_is_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "buildsys source"
            source.mkdir()
            (source / "main.py").write_text(
                'import json, sys\n'
                'print(json.dumps([sys.prefix, sys.argv[1:]]))\nsys.exit(7)\n', encoding="utf-8",
            )
            virtualenv = source / ".venv"
            venv.EnvBuilder(with_pip=False).create(virtualenv)
            (virtualenv / "Scripts/activate.bat").write_bytes(
                b'@echo off\r\necho activated>>"%ACTIVATION_LOG%"\r\nexit /b 0\r\n'
            )
            project = base / "project with spaces &!"
            project.mkdir()
            with patch("task.install.BUILDSYS_DIR", source):
                install_wrappers(project)
            activation_log = base / "activations"
            for active in (None, "", str(base / "another .venv"), str(virtualenv),
                           str(virtualenv).upper(), str(virtualenv) + "\\", str(virtualenv) + "\\.",
                           os.path.relpath(virtualenv, base)):
                with self.subTest(active=active):
                    activation_log.unlink(missing_ok=True)
                    env = dict(os.environ, ACTIVATION_LOG=str(activation_log))
                    env.pop("VIRTUAL_ENV", None)
                    if active is not None:
                        env["VIRTUAL_ENV"] = active
                    batch = project / "buildsys.bat"
                    command = (f'"{os.environ["COMSPEC"]}" /d /s /c '
                               f'""{batch}" first "two words" "a&b""')
                    result = subprocess.run(command, cwd=base, env=env, capture_output=True,
                                            text=True, timeout=20)
                    self.assertEqual(result.returncode, 7, result.stderr)
                    prefix, arguments = json.loads(result.stdout)
                    self.assertEqual(Path(prefix).resolve(), virtualenv.resolve())
                    self.assertEqual(Path(arguments[1]).resolve(), project.resolve())
                    self.assertEqual(arguments[2:], ["first", "two words", "a&b"])
                    expected_activation = active in (None, "", str(base / "another .venv"))
                    self.assertEqual(activation_log.exists(), expected_activation)
                    if expected_activation:
                        self.assertEqual(activation_log.read_text(), "activated\n")

    @unittest.skipUnless(os.name == "nt", "Requires Windows cmd.exe")
    def test_batch_forwards_arguments_project_and_failure_from_another_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "tool %literal%!"
            source.mkdir()
            (source / "main.py").write_text(
                'import json, sys\nfrom pathlib import Path\n'
                'print(json.dumps([str(Path(sys.argv[2]).resolve()), sys.argv[3:]]))\n'
                'sys.exit(7)\n', encoding="utf-8",
            )
            project = base / "project with spaces &!"
            project.mkdir()
            with patch("task.install.BUILDSYS_DIR", source):
                install_wrappers(project)
            batch = project / "buildsys.bat"
            command = (f'"{os.environ["COMSPEC"]}" /d /s /c '
                       f'""{batch}" first "two words" "a&b""')
            result = subprocess.run(command, cwd=base, capture_output=True, text=True)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(json.loads(result.stdout), [str(project.resolve()), ["first", "two words", "a&b"]])


if __name__ == "__main__":
    unittest.main()
