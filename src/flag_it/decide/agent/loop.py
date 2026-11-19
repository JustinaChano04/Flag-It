"""The agent's tool loop (contracts.md step 7).

The model works with the tools and ends by calling submit_verdicts, whose arguments are forced into the
AgentOutput schema. Tool calls are bounded by settings.max_tool_calls: once reached, the next request
forces submit_verdicts, so the model answers with what it has (a check it can't settle is unsure, which
sends the run to a person). An invalid answer (a schema error, or a missing or extra check) is sent back as
an error and the model gets one retry; the second failure is InvalidOutput.
"""

from collections.abc import Sequence
from typing import Protocol

from pydantic import ValidationError

from flag_it.contracts.decide import AgentOutput
from flag_it.contracts.rules import AgentSettings
from flag_it.decide.agent.llm import LlmClient, Message, ToolResult, ToolSpec, ToolUse
from flag_it.decide.agent.prompt import SUBMIT, submit_spec


class InvalidOutput(Exception):
    """The model's answer failed validation, again after one retry."""


class Toolbox(Protocol):
    def specs(self) -> Sequence[ToolSpec]: ...

    def call(self, use: ToolUse) -> ToolResult: ...


def _problems(arguments: dict, check_ids: Sequence[str]) -> tuple[AgentOutput | None, str | None]:
    try:
        output = AgentOutput.model_validate(arguments)
    except ValidationError as error:
        first = error.errors()[0]
        return None, f"invalid answer: {first['msg']} (at {'.'.join(str(p) for p in first['loc'])})"
    got, wanted = {v.check_id for v in output.verdicts}, set(check_ids)
    if got != wanted:
        return None, (
            f"invalid answer: give exactly one verdict for each of {sorted(wanted)}; "
            f"missing {sorted(wanted - got)}, not asked for {sorted(got - wanted)}"
        )
    return output, None


def run_agent(
    client: LlmClient,
    *,
    system: str,
    user_message: str,
    toolbox: Toolbox,
    settings: AgentSettings,
    check_ids: Sequence[str],
) -> AgentOutput:
    messages: list[Message] = [Message("user", user_message)]
    tools = (*toolbox.specs(), submit_spec())
    calls = 0
    retried = False
    while True:
        force = SUBMIT if calls >= settings.max_tool_calls else None
        reply = client.complete(system=system, messages=messages, tools=tools, force_tool=force)
        # An assistant message with no text and no tool calls is an empty content list, which the API rejects.
        messages.append(Message("assistant", reply.text or ("" if reply.tool_uses else "(no answer)"), reply.tool_uses))
        submitted = next((u for u in reply.tool_uses if u.name == SUBMIT), None)
        if submitted is None:
            if not reply.tool_uses:  # prose only
                if retried:
                    raise InvalidOutput("the model did not submit an answer")
                retried = True
                messages.append(Message("user", f"Answer by calling {SUBMIT}."))
                continue
            results: list[ToolResult] = []
            for use in reply.tool_uses:
                if calls >= settings.max_tool_calls:
                    results.append(ToolResult(use.id, "tool call limit reached: answer now", True))
                else:
                    calls += 1
                    results.append(toolbox.call(use))
            messages.append(Message("user", tool_results=tuple(results)))
            continue
        output, problem = _problems(dict(submitted.arguments), check_ids)
        if output is not None:
            return output
        if retried:
            raise InvalidOutput(problem)
        retried = True
        messages.append(
            Message(
                "user",
                tool_results=tuple(
                    ToolResult(u.id, problem if u.id == submitted.id else "not run: fix your answer first", True)
                    for u in reply.tool_uses
                ),
            )
        )
