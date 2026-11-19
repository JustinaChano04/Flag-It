"""A scripted model for tests: it returns the replies it was given, in order, and records what it was asked."""

from collections.abc import Sequence
from typing import Any

from flag_it.decide.agent.llm import Message, Reply, ToolSpec, ToolUse

SUBMIT = "submit_verdicts"


class ScriptedClient:
    model_tag = "scripted-1"

    def __init__(self, *replies: Reply | Exception) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec], force_tool: str | None = None
    ) -> Reply:
        self.calls.append(
            {"system": system, "messages": tuple(messages), "tools": tuple(t.name for t in tools), "force_tool": force_tool}
        )
        nxt = self._replies.pop(0)  # an IndexError here means the code asked the model more than the test expected
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def use(id: str, name: str, **arguments: Any) -> ToolUse:
    return ToolUse(id=id, name=name, arguments=arguments)


def reply(*tool_uses: ToolUse, text: str = "") -> Reply:
    return Reply(text=text, tool_uses=tuple(tool_uses))


def verdict(check_id: str, result: str, confidence: float, *evidence: dict) -> dict:
    return {"check_id": check_id, "result": result, "confidence": confidence, "evidence": list(evidence)}


def submit(*verdicts: dict, id: str = "tu_submit") -> Reply:
    return reply(use(id, SUBMIT, verdicts=list(verdicts)))
