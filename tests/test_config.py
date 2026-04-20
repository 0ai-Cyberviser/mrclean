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
        # Check multi-model configuration
        self.assertEqual(len(config.models), 2)
        self.assertEqual(config.models[0].name, "gpt-5.4-turbo")
        self.assertIn("security", config.models[0].task_types)
        self.assertEqual(config.models[0].priority, 100)

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

    def test_multi_model_routing_selects_best_match(self) -> None:
        config_text = """name = "mrclean"

[model]
provider = "openai"
name = "gpt-5.4-mini"

[[models]]
provider = "openai"
name = "gpt-5.4-turbo"
task_types = ["security", "vulnerability"]
priority = 100

[[models]]
provider = "openai"
name = "gpt-5.4-mini"
task_types = ["planning", "proposal"]
priority = 50

[policy]
dry_run = true

[[repositories]]
name = "example/repo"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "multi.toml"
            path.write_text(config_text, encoding="utf-8")
            config = MrCleanConfig.from_toml(path)

        # Should select high-priority security model for security tasks
        security_model = config.get_model_for_task("security")
        self.assertEqual(security_model.name, "gpt-5.4-turbo")
        self.assertEqual(security_model.priority, 100)

        # Should select planning model for planning tasks
        planning_model = config.get_model_for_task("planning")
        self.assertEqual(planning_model.name, "gpt-5.4-mini")
        self.assertEqual(planning_model.priority, 50)

        # Should fall back to default model for unknown tasks
        unknown_model = config.get_model_for_task("unknown")
        self.assertEqual(unknown_model.name, "gpt-5.4-mini")


if __name__ == "__main__":
    unittest.main()
