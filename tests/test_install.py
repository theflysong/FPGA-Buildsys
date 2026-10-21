"""Native Windows batch forwarding and exit status."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from task.install import install_wrappers


class BatchWrapperTests(unittest.TestCase):
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
