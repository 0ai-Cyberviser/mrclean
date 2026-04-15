from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from mrclean.cli import main


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


if __name__ == "__main__":
    unittest.main()

