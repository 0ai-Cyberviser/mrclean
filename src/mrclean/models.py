from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Protocol


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class CompletionRequest:
    model: str
    temperature: float
    max_tokens: int
    messages: tuple[ChatMessage, ...]


@dataclass(slots=True)
class CompletionResponse:
    content: str
    raw: dict[str, Any] = field(default_factory=dict)


class ModelClient(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Return a completion for the provided request."""


class StubModelClient:
    """Deterministic local client used before a real provider is wired in."""

    def __init__(self, provider_hint: str = "stub", reason: str = "") -> None:
        self.provider_hint = provider_hint
        self.reason = reason

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        system_prompt = request.messages[0].content if request.messages else ""
        user_messages = [message.content.strip() for message in request.messages if message.role == "user"]
        summary = user_messages[-1] if user_messages else "No repo context provided."
        first_changed_file = _extract_first_changed_file(summary)
        if "edit proposal" in system_prompt.lower():
            content = (
                "Summary\n"
                "- Narrow the fix to the active CI or review signal described in the context.\n\n"
                "Proposed Edits\n"
                "- Edit only the files already implicated by the current branch diff or failing checks.\n"
                "- Preserve the existing policy gates and avoid widening scope.\n\n"
                "Validation\n"
                "- Re-run the smallest targeted tests or checks that cover the proposed edit.\n"
                "- Confirm the local workspace still matches the PR branch before any write step.\n\n"
                "Risks\n"
                f"- Stub output only. Review the captured context manually before editing.\n"
                f"- Context source: {summary[:240]}"
            )
        elif "guarded file-write bundle" in system_prompt.lower():
            content = json.dumps(_build_stub_draft_payload(summary), indent=2)
        elif "machine-readable edit intent" in system_prompt.lower():
            content = json.dumps(
                {
                    "summary": "Narrow the fix to the active failure signal using the current branch scope.",
                    "edits": [
                        {
                            "path": first_changed_file or "REVIEW_REQUIRED",
                            "operation": "modify",
                            "summary": "Inspect the current branch diff and update only the directly implicated file.",
                            "reason": f"Stub output only. Derive the exact file from context: {summary[:180]}",
                        }
                    ],
                    "validation": [
                        "Re-run the smallest targeted tests or CI checks related to the failing signal.",
                        "Confirm the local workspace still matches the PR branch before editing.",
                    ],
                    "risks": [
                        "Stub output only. Verify the proposed file path against the current branch diff before applying.",
                        "Do not widen scope beyond the files already implicated by the current branch diff.",
                    ],
                },
                indent=2,
            )
        else:
            content = (
                "MrClean stub plan\n"
                "- inspect the failing signal\n"
                "- keep edits narrow and reversible\n"
                "- validate before any push\n"
                f"- context: {summary}"
            )
        return CompletionResponse(
            content=content,
            raw={"provider": "stub", "model": request.model, "provider_hint": self.provider_hint, "reason": self.reason},
        )


class OpenAIChatModelClient:
    def __init__(self, api_key: str, base_url: str = "") -> None:
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = self.client.chat.completions.create(
            model=request.model,
            messages=[{"role": message.role, "content": message.content} for message in request.messages],
            temperature=request.temperature,
            max_completion_tokens=request.max_tokens,
        )
        message = response.choices[0].message
        return CompletionResponse(
            content=message.content or "",
            raw={
                "provider": "openai",
                "model": getattr(response, "model", request.model),
                "id": getattr(response, "id", ""),
            },
        )


class AnthropicModelClient:
    def __init__(self, api_key: str) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ImportError("anthropic package required for Claude integration: pip install anthropic") from exc
        self.client = Anthropic(api_key=api_key)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        # Convert messages to Anthropic format
        system_message = ""
        messages_list = []
        for msg in request.messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                messages_list.append({"role": msg.role, "content": msg.content})

        response = self.client.messages.create(
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=system_message if system_message else None,
            messages=messages_list,
        )
        content = response.content[0].text if response.content else ""
        return CompletionResponse(
            content=content,
            raw={
                "provider": "anthropic",
                "model": response.model,
                "id": response.id,
            },
        )


class GoogleGeminiModelClient:
    def __init__(self, api_key: str) -> None:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise ImportError("google-generativeai package required for Gemini: pip install google-generativeai") from exc
        genai.configure(api_key=api_key)
        self.genai = genai

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        # Gemini combines system and user messages
        model = self.genai.GenerativeModel(request.model)
        prompt_parts = []
        for msg in request.messages:
            if msg.role == "system":
                prompt_parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")

        combined_prompt = "\n\n".join(prompt_parts)
        response = model.generate_content(
            combined_prompt,
            generation_config={
                "temperature": request.temperature,
                "max_output_tokens": request.max_tokens,
            },
        )
        content = response.text if hasattr(response, "text") else ""
        return CompletionResponse(
            content=content,
            raw={
                "provider": "google_gemini",
                "model": request.model,
            },
        )


class GitHubCopilotModelClient:
    def __init__(self, api_key: str, base_url: str = "https://api.githubcopilot.com") -> None:
        from openai import OpenAI
        # GitHub Copilot uses OpenAI-compatible API
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = self.client.chat.completions.create(
            model=request.model,
            messages=[{"role": message.role, "content": message.content} for message in request.messages],
            temperature=request.temperature,
            max_completion_tokens=request.max_tokens,
        )
        message = response.choices[0].message
        return CompletionResponse(
            content=message.content or "",
            raw={
                "provider": "github_copilot",
                "model": getattr(response, "model", request.model),
                "id": getattr(response, "id", ""),
            },
        )


def build_model_client(provider: str, model_name: str, env: dict[str, str] | None = None) -> ModelClient:
    environment = env or os.environ
    normalized = provider.strip().lower()
    if normalized == "openai":
        api_key = environment.get("OPENAI_API_KEY", "")
        if not api_key:
            return StubModelClient(provider_hint="openai", reason="OPENAI_API_KEY is not configured")
        base_url = environment.get("OPENAI_BASE_URL", "")
        return OpenAIChatModelClient(api_key=api_key, base_url=base_url)
    if normalized in {"anthropic", "claude"}:
        api_key = environment.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return StubModelClient(provider_hint="anthropic", reason="ANTHROPIC_API_KEY is not configured")
        return AnthropicModelClient(api_key=api_key)
    if normalized in {"google", "gemini", "google_gemini"}:
        api_key = environment.get("GOOGLE_API_KEY", "") or environment.get("GEMINI_API_KEY", "")
        if not api_key:
            return StubModelClient(provider_hint="google_gemini", reason="GOOGLE_API_KEY or GEMINI_API_KEY is not configured")
        return GoogleGeminiModelClient(api_key=api_key)
    if normalized in {"github_copilot", "copilot"}:
        api_key = environment.get("GITHUB_COPILOT_API_KEY", "") or environment.get("COPILOT_API_KEY", "")
        if not api_key:
            return StubModelClient(provider_hint="github_copilot", reason="GITHUB_COPILOT_API_KEY or COPILOT_API_KEY is not configured")
        base_url = environment.get("GITHUB_COPILOT_BASE_URL", "https://api.githubcopilot.com")
        return GitHubCopilotModelClient(api_key=api_key, base_url=base_url)
    if normalized in {"stub", ""}:
        return StubModelClient(provider_hint=normalized or "stub")
    return StubModelClient(provider_hint=provider, reason=f"unsupported provider {provider!r} for model {model_name}")


def _extract_first_changed_file(summary: str) -> str:
    marker = "Changed files:"
    for line in summary.splitlines():
        if not line.startswith(marker):
            continue
        files = [item.strip() for item in line[len(marker) :].split(",")]
        for file_path in files:
            if file_path and file_path.lower() != "none":
                return file_path
    return ""


def _build_stub_draft_payload(summary: str) -> dict[str, Any]:
    payload = _parse_json_object(summary)
    edits = payload.get("edits", [])
    operations: list[dict[str, Any]] = []
    if isinstance(edits, list):
        for item in edits:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            operation = str(item.get("operation", "modify")).strip() or "modify"
            current_content = item.get("current_content")
            current_text = current_content if isinstance(current_content, str) else ""
            action = "delete_file" if operation == "delete" else "write_file"
            entry: dict[str, Any] = {
                "path": path or "REVIEW_REQUIRED",
                "action": action,
                "summary": "Draft the narrowest reversible file change for the active signal.",
                "reason": f"Stub output only. Use the materialized file target from context: {(path or 'REVIEW_REQUIRED')[:180]}",
            }
            if action == "write_file":
                entry["content"] = _stub_write_content(path, current_text, operation)
            operations.append(entry)

    if not operations:
        operations.append(
            {
                "path": "REVIEW_REQUIRED",
                "action": "write_file",
                "summary": "Draft a narrow fix for manual review.",
                "reason": "Stub output only. No materialized edit targets were provided in the context.",
                "content": "# MrClean stub draft: replace with a reviewed fix.\n",
            }
        )

    return {
        "summary": "Convert the materialized intent into explicit write/delete operations without applying them.",
        "operations": operations,
        "validation": [
            "Re-run the smallest targeted tests or CI checks related to the active signal.",
            "Verify the expected file hashes still match before applying any generated write step.",
        ],
        "risks": [
            "Stub output only. Review the generated file content before any apply step.",
            "Do not widen scope beyond the materialized file targets.",
        ],
    }


def _stub_write_content(path: str, current_content: str, operation: str) -> str:
    prefix = _comment_prefix_for_path(path)
    note = f"{prefix} MrClean stub draft: replace with the reviewed narrow fix.\n"
    if operation == "create" and not current_content:
        return note
    if not current_content:
        return note
    if current_content.endswith("\n"):
        return current_content + note
    return current_content + "\n" + note


def _comment_prefix_for_path(path: str) -> str:
    normalized = path.lower()
    if normalized.endswith(
        (
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".c",
            ".cc",
            ".cpp",
            ".h",
            ".hpp",
            ".go",
            ".rs",
            ".swift",
            ".kt",
            ".kts",
        )
    ):
        return "//"
    return "#"


def _parse_json_object(summary: str) -> dict[str, Any]:
    try:
        payload = json.loads(summary)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload
