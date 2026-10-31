"""Virtual environment initialization uses the buildsys installation directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from task import init_venv
from task.install import install_wrappers


class InitVenvTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Requires Linux Bash and /dev/shm")
    def test_shell_wrapper_uses_buildsys_environment_and_project_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "buildsys source"
            project = base / "project"
            source.mkdir()
            project.mkdir()
            (source / "main.py").write_text("# fake entry\n")
            scripts = source / ".venv/bin"
            scripts.mkdir(parents=True)
            (scripts / ("activate.bat" if os.name == "nt" else "activate")).write_text(
                f'VIRTUAL_ENV="{source / ".venv"}"; export VIRTUAL_ENV\n'
            )
            fake_python = scripts / ("python.exe" if os.name == "nt" else "python")
            fake_python.write_text(
                '#!/usr/bin/env bash\n'
                'printf "%s\\n" "$VIRTUAL_ENV" > "$VENV_MARKER"\n'
                'printf "%s\\n" "$PWD" >> "$VENV_MARKER"\n'
            )
            fake_python.chmod(0o755)
            marker = base / "marker"
            with patch("task.install.BUILDSYS_DIR", source):
                install_wrappers(project)
            result = subprocess.run(
                [str(project / "buildsys.sh"), "init-venv"], cwd=base,
                env={**os.environ, "VENV_MARKER": str(marker)},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text().splitlines(), [str(source / ".venv"), str(base)])

    def test_creates_environment_and_installs_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_text("pytcl-eda==0.3.0\n")
            calls: list[list[str]] = []

            class Builder:
                def __init__(self, **kwargs: object) -> None:
                    self.kwargs = kwargs

                def create(self, path: Path) -> None:
                    scripts = path / ("Scripts" if os.name == "nt" else "bin")
                    scripts.mkdir(parents=True)
                    (scripts / ("python.exe" if os.name == "nt" else "python")).touch()
                    (scripts / ("activate.bat" if os.name == "nt" else "activate")).touch()

            def pip(command: list[str], **kwargs: object) -> None:
                calls.append(command)

            with patch.object(init_venv, "BUILDSYS_DIR", root), \
                 patch.object(init_venv.venv, "EnvBuilder", Builder), \
                 patch.object(init_venv.subprocess, "run", pip):
                self.assertEqual(init_venv.run(argparse.Namespace()), 0)

            self.assertEqual(calls, [[
                str(root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")), "-m", "pip", "install", "-r",
                str(root / "requirements.txt"),
            ]])

    def test_reuses_complete_environment_without_recreating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_text("pytcl-eda==0.3.0\n")
            scripts = root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
            scripts.mkdir(parents=True)
            (scripts / ("python.exe" if os.name == "nt" else "python")).touch()
            (scripts / ("activate.bat" if os.name == "nt" else "activate")).touch()
            with patch.object(init_venv, "BUILDSYS_DIR", root), \
                 patch.object(init_venv.venv, "EnvBuilder") as builder, \
                 patch.object(init_venv.subprocess, "run") as pip:
                self.assertEqual(init_venv.run(argparse.Namespace()), 0)
            builder.assert_not_called()
            pip.assert_called_once()

    def test_reports_dependency_install_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_text("pytcl-eda==0.3.0\n")
            scripts = root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
            scripts.mkdir(parents=True)
            (scripts / ("python.exe" if os.name == "nt" else "python")).touch()
            (scripts / ("activate.bat" if os.name == "nt" else "activate")).touch()
            failure = subprocess.CalledProcessError(9, ["pip"])
            with patch.object(init_venv, "BUILDSYS_DIR", root), \
                 patch.object(init_venv.subprocess, "run", side_effect=failure):
                with self.assertRaises(subprocess.CalledProcessError):
                    init_venv.run(argparse.Namespace())


if __name__ == "__main__":
    unittest.main()
