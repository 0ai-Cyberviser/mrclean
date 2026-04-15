from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from mrclean.config import MrCleanConfig, sample_config


class ConfigTests(unittest.TestCase):
    def test_sample_config_parses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mrclean.toml"
            path.write_text(sample_config(), encoding="utf-8")
            config = MrCleanConfig.from_toml(path)

        self.assertEqual(config.name, "mrclean")
        self.assertEqual(config.model.name, "gpt-5.4-mini")
        self.assertEqual(len(config.repositories), 2)
        self.assertEqual(
            config.get_repository("0ai-Cyberviser/Hancock").monitored_checks,
            ("build-linux", "oss-fuzz", "cifuzz", "fuzzing"),
        )

    def test_invalid_force_push_policy_is_rejected(self) -> None:
        invalid = """name = "mrclean"

[model]
provider = "openai"
name = "gpt-5.4-mini"

[policy]
allow_push = false
allow_force_push = true

[[repositories]]
name = "example/repo"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.toml"
            path.write_text(invalid, encoding="utf-8")
            with self.assertRaises(ValueError):
                MrCleanConfig.from_toml(path)


if __name__ == "__main__":
    unittest.main()
