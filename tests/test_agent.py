from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from mrclean.agent import CleanupSignal, MrCleanAgent
from mrclean.config import MrCleanConfig, sample_config


class AgentTests(unittest.TestCase):
    def test_agent_generates_policy_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mrclean.toml"
            path.write_text(sample_config(), encoding="utf-8")
            config = MrCleanConfig.from_toml(path)

        repository = config.get_repository("0ai-Cyberviser/Hancock")
        plan = MrCleanAgent(config).draft_plan(
            CleanupSignal(
                repository=repository,
                goal="stabilize failing CI",
                branch="codex/ci-fix",
                failing_checks=("build-linux",),
                changed_files=("hancock_agent.py",),
            )
        )

        self.assertEqual(plan.repository, "0ai-Cyberviser/Hancock")
        self.assertTrue(any(action.kind == "push_commit" for action in plan.actions))
        self.assertTrue(any("push is disabled by policy" in note for note in plan.policy_notes))


if __name__ == "__main__":
    unittest.main()

