from __future__ import annotations

from dataclasses import dataclass, field
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

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        user_messages = [message.content.strip() for message in request.messages if message.role == "user"]
        summary = user_messages[-1] if user_messages else "No repo context provided."
        content = (
            "MrClean stub plan\n"
            "- inspect the failing signal\n"
            "- keep edits narrow and reversible\n"
            "- validate before any push\n"
            f"- context: {summary}"
        )
        return CompletionResponse(content=content, raw={"provider": "stub", "model": request.model})

