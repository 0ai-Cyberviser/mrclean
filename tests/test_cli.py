from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mrclean.cli import main
from mrclean.monitor import ScanResult
from mrclean.watch import WatchEvent

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

    def test_watch_command_renders_event_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mrclean.toml"
            config_path.write_text((PROJECT_ROOT / "mrclean.toml.example").read_text(encoding="utf-8"), encoding="utf-8")

            item = ScanResult(
                repository="example/repo",
                number=32,
                title="Fix CI",
                url="https://github.com/example/repo/pull/32",
                branch="fix-ci",
                updated_at="2026-04-15T18:00:00Z",
                merge_state_status="UNSTABLE",
                category="needs_attention",
                failing_checks=("build-linux",),
                pending_checks=(),
            )
            event = WatchEvent(
                iteration=1,
                kind="appeared",
                repository="example/repo",
                number=32,
                current=item,
            )

            class FakeWatcher:
                iteration = 0

                def __init__(self, scanner) -> None:
                    self.iteration = 0

                def poll(self, repositories=None, include_healthy=False):
                    self.iteration = 1
                    return (event,)

            buffer = StringIO()
            with patch("mrclean.cli.RepositoryWatcher", FakeWatcher):
                with redirect_stdout(buffer):
                    result = main(["watch", str(config_path), "--iterations", "1", "--interval", "0"])

            self.assertEqual(result, 0)
            output = buffer.getvalue()
            self.assertIn("Iteration 1: appeared example/repo#32", output)
            self.assertIn("Failing checks: build-linux", output)


if __name__ == "__main__":
    unittest.main()
