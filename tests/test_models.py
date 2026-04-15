from __future__ import annotations

import json
import unittest

from mrclean.models import ChatMessage, CompletionRequest, OpenAIChatModelClient, StubModelClient, build_model_client


class ModelFactoryTests(unittest.TestCase):
    def test_build_model_client_falls_back_to_stub_without_api_key(self) -> None:
        client = build_model_client("openai", "gpt-5.4-mini", env={})
        self.assertIsInstance(client, StubModelClient)

    def test_build_model_client_returns_stub_for_unknown_provider(self) -> None:
        client = build_model_client("unknown", "test-model", env={})
        self.assertIsInstance(client, StubModelClient)

    def test_build_model_client_returns_openai_client_when_key_exists(self) -> None:
        client = build_model_client("openai", "gpt-5.4-mini", env={"OPENAI_API_KEY": "test-key"})
        self.assertIsInstance(client, OpenAIChatModelClient)

    def test_stub_model_returns_structured_proposal_for_proposal_prompt(self) -> None:
        response = StubModelClient().complete(
            CompletionRequest(
                model="gpt-5.4-mini",
                temperature=0.1,
                max_tokens=1000,
                messages=(
                    ChatMessage(role="system", content="You are generating an edit proposal."),
                    ChatMessage(role="user", content="Repository: example/repo"),
                ),
            )
        )
        self.assertIn("Summary", response.content)
        self.assertIn("Proposed Edits", response.content)
        self.assertIn("Validation", response.content)
        self.assertIn("Risks", response.content)

    def test_stub_model_returns_json_for_intent_prompt(self) -> None:
        response = StubModelClient().complete(
            CompletionRequest(
                model="gpt-5.4-mini",
                temperature=0.1,
                max_tokens=1000,
                messages=(
                    ChatMessage(role="system", content="You are generating a machine-readable edit intent."),
                    ChatMessage(role="user", content="Repository: example/repo"),
                ),
            )
        )
        self.assertIn('"summary"', response.content)
        self.assertIn('"edits"', response.content)
        self.assertIn('"validation"', response.content)
        self.assertIn('REVIEW_REQUIRED', response.content)

    def test_stub_model_prefers_first_changed_file_for_intent_prompt(self) -> None:
        response = StubModelClient().complete(
            CompletionRequest(
                model="gpt-5.4-mini",
                temperature=0.1,
                max_tokens=1000,
                messages=(
                    ChatMessage(role="system", content="You are generating a machine-readable edit intent."),
                    ChatMessage(role="user", content="Changed files: requirements-dev.txt, tests/test_api.py"),
                ),
            )
        )
        self.assertIn('"path": "requirements-dev.txt"', response.content)

    def test_stub_model_returns_json_for_draft_prompt(self) -> None:
        response = StubModelClient().complete(
            CompletionRequest(
                model="gpt-5.4-mini",
                temperature=0.1,
                max_tokens=1000,
                messages=(
                    ChatMessage(role="system", content="You are generating a guarded file-write bundle."),
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "repository": "example/repo",
                                "edits": [
                                    {
                                        "path": "Dockerfile",
                                        "operation": "modify",
                                        "current_content": "FROM python:3.12\n",
                                    }
                                ],
                            }
                        ),
                    ),
                ),
            )
        )
        self.assertIn('"operations"', response.content)
        self.assertIn('"action": "write_file"', response.content)
        self.assertIn('"path": "Dockerfile"', response.content)


if __name__ == "__main__":
    unittest.main()
