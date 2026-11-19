"""The language-model interface the agent depends on.

The agent sends a conversation and a list of tools and gets back text and tool calls. Nothing here
names a provider: a second provider is another adapter, and tests use a scripted fake. A caller may
`force_tool`, which makes the model answer by calling that tool.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]  # JSON Schema of the arguments


@dataclass(frozen=True)
class ToolUse:
    """The model asking to call a tool. `id` is chosen by the provider and is what a citation names."""

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str = ""
    tool_uses: tuple[ToolUse, ...] = ()  # assistant messages only
    tool_results: tuple[ToolResult, ...] = ()  # user messages only


@dataclass(frozen=True)
class Reply:
    text: str = ""
    tool_uses: tuple[ToolUse, ...] = ()


class LlmUnavailable(Exception):
    """The model could not be reached or refused the request, after the provider SDK's own retries."""


class LlmClient(Protocol):
    @property
    def model_tag(self) -> str: ...

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        force_tool: str | None = None,
    ) -> Reply: ...
