from __future__ import annotations

import unittest

from mrclean.config import MrCleanConfig, sample_config
from mrclean.dispatch import DispatchAction, DispatchCandidate
from mrclean.models import CompletionResponse
from mrclean.proposals import ProposalGenerator
from mrclean.runner import ActionExecution, RunSession


class FakeModel:
    def complete(self, request):
        return CompletionResponse(
            content="Summary\n- narrow fix\n\nProposed Edits\n- touch one file\n\nValidation\n- run tests\n\nRisks\n- low",
            raw={"provider": "fake", "model": request.model},
        )


class ProposalGeneratorTests(unittest.TestCase):
    def test_proposal_generator_builds_proposal_from_candidate_and_session(self) -> None:
        config = MrCleanConfig.from_toml_text(sample_config())
        candidate = DispatchCandidate(
            repository="example/repo",
            number=32,
            title="Fix CI",
            url="https://github.com/example/repo/pull/32",
            branch="fix-ci",
            category="needs_attention",
            status="ready",
            priority=0,
            workspace_ready=True,
            workspace_reason="workspace matches PR branch",
            changed_files=("a.py",),
            actions=(
                DispatchAction("inspect_signal", "inspect", True, "allowed", "gh pr view 32"),
                DispatchAction("edit_patch", "edit", True, "allowed", "git diff --stat"),
            ),
        )
        session = RunSession(
            repository="example/repo",
            number=32,
            branch="fix-ci",
            candidate_status="ready",
            run_status="prepared",
            executions=(
                ActionExecution(
                    kind="inspect_signal",
                    summary="inspect",
                    command="gh pr view 32",
                    status="executed",
                    reason="command completed successfully",
                    returncode=0,
                    stdout="review context",
                    stderr="",
                ),
            ),
        )

        proposal = ProposalGenerator(config, model_client=FakeModel()).generate(candidate, session)
        self.assertEqual(proposal.repository, "example/repo")
        self.assertEqual(proposal.number, 32)
        self.assertEqual(proposal.model_provider, "fake")
        self.assertIn("Proposed Edits", proposal.content)


if __name__ == "__main__":
    unittest.main()
