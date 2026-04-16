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
        self.assertEqual(len(config.repositories), 4)
        self.assertFalse(config.policy.allow_local_apply)
        self.assertTrue(config.policy.require_signed_preview_artifacts)
        self.assertEqual(config.policy.artifact_signing_key_env, "MRCLEAN_ARTIFACT_SIGNING_KEY")
        self.assertEqual(
            config.get_repository("0ai-Cyberviser/Hancock").monitored_checks,
            ("build-linux", "oss-fuzz", "cifuzz", "fuzzing"),
        )
        self.assertEqual(
            config.get_repository("xai-org/grok-1").authors,
            ("0ai-Cyberviser",),
        )
        self.assertEqual(
            config.get_repository("0ai-Cyberviser/CyberViser-ViserHub").authors,
            ("0ai-Cyberviser", "app/copilot-swe-agent"),
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

    def test_missing_signing_key_env_is_rejected_when_signatures_are_required(self) -> None:
        invalid = """name = "mrclean"

[model]
provider = "openai"
name = "gpt-5.4-mini"

[policy]
require_signed_preview_artifacts = true
artifact_signing_key_env = ""

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
