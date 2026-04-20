from __future__ import annotations

import json
import unittest

from mrclean.models import (
    AnthropicModelClient,
    ChatMessage,
    CompletionRequest,
    GitHubCopilotModelClient,
    GoogleGeminiModelClient,
    OpenAIChatModelClient,
    StubModelClient,
    build_model_client,
)


class ModelFactoryTests(unittest.TestCase):
    def test_build_model_client_falls_back_to_stub_without_api_key(self) -> None:
        client = build_model_client("openai", "gpt-5.4-mini", env={})
        self.assertIsInstance(client, StubModelClient)

    def test_build_model_client_returns_stub_for_unknown_provider(self) -> None:
        client = build_model_client("unknown", "test-model", env={})
        self.assertIsInstance(client, StubModelClient)

    def test_build_model_client_returns_openai_client_when_key_exists(self) -> None:
        try:
            client = build_model_client("openai", "gpt-5.4-mini", env={"OPENAI_API_KEY": "test-key"})
            self.assertIsInstance(client, OpenAIChatModelClient)
        except ImportError:
            self.skipTest("openai package not installed")

    def test_build_model_client_returns_anthropic_client_when_key_exists(self) -> None:
        try:
            client = build_model_client("anthropic", "claude-3-5-sonnet-20241022", env={"ANTHROPIC_API_KEY": "test-key"})
            self.assertIsInstance(client, AnthropicModelClient)
        except ImportError:
            self.skipTest("anthropic package not installed")

    def test_build_model_client_returns_anthropic_client_for_claude_alias(self) -> None:
        try:
            client = build_model_client("claude", "claude-3-5-sonnet-20241022", env={"ANTHROPIC_API_KEY": "test-key"})
            self.assertIsInstance(client, AnthropicModelClient)
        except ImportError:
            self.skipTest("anthropic package not installed")

    def test_build_model_client_returns_gemini_client_when_key_exists(self) -> None:
        try:
            client = build_model_client("gemini", "gemini-1.5-pro", env={"GOOGLE_API_KEY": "test-key"})
            self.assertIsInstance(client, GoogleGeminiModelClient)
        except ImportError:
            self.skipTest("google-generativeai package not installed")

    def test_build_model_client_returns_gemini_client_for_google_alias(self) -> None:
        try:
            client = build_model_client("google", "gemini-1.5-pro", env={"GEMINI_API_KEY": "test-key"})
            self.assertIsInstance(client, GoogleGeminiModelClient)
        except ImportError:
            self.skipTest("google-generativeai package not installed")

    def test_build_model_client_returns_copilot_client_when_key_exists(self) -> None:
        try:
            client = build_model_client("copilot", "gpt-4", env={"COPILOT_API_KEY": "test-key"})
            self.assertIsInstance(client, GitHubCopilotModelClient)
        except ImportError:
            self.skipTest("openai package not installed")

    def test_build_model_client_returns_copilot_client_for_github_copilot_alias(self) -> None:
        try:
            client = build_model_client("github_copilot", "gpt-4", env={"GITHUB_COPILOT_API_KEY": "test-key"})
            self.assertIsInstance(client, GitHubCopilotModelClient)
        except ImportError:
            self.skipTest("openai package not installed")

    def test_build_model_client_falls_back_to_stub_for_anthropic_without_key(self) -> None:
        client = build_model_client("anthropic", "claude-3-5-sonnet-20241022", env={})
        self.assertIsInstance(client, StubModelClient)
        self.assertIn("ANTHROPIC_API_KEY", client.reason)

    def test_build_model_client_falls_back_to_stub_for_gemini_without_key(self) -> None:
        client = build_model_client("gemini", "gemini-1.5-pro", env={})
        self.assertIsInstance(client, StubModelClient)
        self.assertIn("GOOGLE_API_KEY", client.reason)

    def test_build_model_client_falls_back_to_stub_for_copilot_without_key(self) -> None:
        client = build_model_client("copilot", "gpt-4", env={})
        self.assertIsInstance(client, StubModelClient)
        self.assertIn("COPILOT_API_KEY", client.reason)

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
