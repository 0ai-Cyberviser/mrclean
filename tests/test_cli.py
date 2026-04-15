from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mrclean.cli import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_init_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            result = main(["init", str(config_path)])
            self.assertEqual(result, 0)

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = main(["validate", str(config_path)])
            self.assertEqual(result, 0)
            self.assertIn("config valid", buffer.getvalue())

    def test_module_entrypoint_executes_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "mrclean.cli", "validate", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            )
            self.assertEqual(completed.returncode, 0)
            self.assertIn("config valid", completed.stdout)


if __name__ == "__main__":
    unittest.main()
