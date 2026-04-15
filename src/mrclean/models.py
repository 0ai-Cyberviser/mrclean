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


def build_model_client(provider: str, model_name: str, env: dict[str, str] | None = None) -> ModelClient:
    environment = env or os.environ
    normalized = provider.strip().lower()
    if normalized == "openai":
        api_key = environment.get("OPENAI_API_KEY", "")
        if not api_key:
            return StubModelClient(provider_hint="openai", reason="OPENAI_API_KEY is not configured")
        base_url = environment.get("OPENAI_BASE_URL", "")
        return OpenAIChatModelClient(api_key=api_key, base_url=base_url)
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
