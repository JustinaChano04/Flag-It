"""The Anthropic adapter for LlmClient. The SDK retries transient errors itself; what is left is LlmUnavailable."""

import os
from collections.abc import Sequence
from typing import Any

import anthropic

from flag_it.decide.agent.llm import LlmUnavailable, Message, Reply, ToolSpec, ToolUse

DEFAULT_MODEL = "claude-sonnet-5-5"  # overridden by the setting FLAG_IT_JUDGE_MODEL


def _blocks(message: Message) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"type": "tool_result", "tool_use_id": r.tool_use_id, "content": r.content, "is_error": r.is_error}
        for r in message.tool_results
    ]
    if message.text:
        blocks.append({"type": "text", "text": message.text})
    blocks += [
        {"type": "tool_use", "id": u.id, "name": u.name, "input": dict(u.arguments)} for u in message.tool_uses
    ]
    return blocks


class AnthropicClient:
    def __init__(self, model: str, *, client: Any = None, max_tokens: int = 4096) -> None:
        self.model_tag = model
        self._client = client if client is not None else anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self._max_tokens = max_tokens

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        force_tool: str | None = None,
    ) -> Reply:
        request: dict[str, Any] = {
            "model": self.model_tag,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": _blocks(m)} for m in messages],
        }
        if tools:
            request["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": dict(t.parameters)} for t in tools
            ]
        if force_tool is not None:
            request["tool_choice"] = {"type": "tool", "name": force_tool}
        try:
            response = self._client.messages.create(**request)
        except anthropic.APIError as error:
            raise LlmUnavailable(f"{type(error).__name__}: {error}") from error
        text = "".join(block.text for block in response.content if block.type == "text")
        uses = tuple(
            ToolUse(id=block.id, name=block.name, arguments=dict(block.input))
            for block in response.content
            if block.type == "tool_use"
        )
        return Reply(text=text, tool_uses=uses)


def default_client() -> AnthropicClient:
    """The client the worker uses: the model from FLAG_IT_JUDGE_MODEL, else DEFAULT_MODEL."""
    return AnthropicClient(os.environ.get("FLAG_IT_JUDGE_MODEL", DEFAULT_MODEL))
