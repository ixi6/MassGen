from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant", "tool"]
    content: Any = None


class ChatCompletionRequest(BaseModel):
    """
    Minimal OpenAI-compatible Chat Completions request model.

    We intentionally accept unknown fields for forward compatibility.
    """

    model_config = ConfigDict(extra="allow")

    model: str = Field(default="massgen")
    messages: list[dict[str, Any]]
    stream: bool = False

    # Tool calling (OpenAI-style)
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    parallel_tool_calls: bool | None = None
