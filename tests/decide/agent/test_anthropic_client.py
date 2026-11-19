"""The Anthropic adapter, tested with a stub in place of the SDK client: no network."""

from types import SimpleNamespace

import anthropic
import pytest

from flag_it.decide.agent.anthropic_client import DEFAULT_MODEL, AnthropicClient
from flag_it.decide.agent.llm import LlmUnavailable, Message, ToolResult, ToolSpec, ToolUse

SPEC = ToolSpec("cardholder_history", "Past transactions.", {"type": "object", "properties": {}})


def stub(response=None, error=None):
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        if error:
            raise error
        return response

    return SimpleNamespace(messages=SimpleNamespace(create=create)), seen


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def test_the_default_model_is_a_setting_default_not_a_guess():
    assert DEFAULT_MODEL == "claude-sonnet-5-5"


def test_a_reply_with_text_and_tool_calls_is_translated():
    sdk, seen = stub(SimpleNamespace(stop_reason="end_turn", content=[text("Looking."), tool_use("tu_1", "cardholder_history", {"limit": 5})]))
    client = AnthropicClient("m-1", client=sdk, max_tokens=100)
    got = client.complete(system="S", messages=[Message("user", "hi")], tools=[SPEC])
    assert got.text == "Looking."
    assert got.tool_uses == (ToolUse("tu_1", "cardholder_history", {"limit": 5}),)
    assert seen["model"] == "m-1" and seen["max_tokens"] == 100 and seen["system"] == "S"
    assert seen["tools"] == [{"name": "cardholder_history", "description": "Past transactions.", "input_schema": SPEC.parameters}]
    assert "tool_choice" not in seen


def test_messages_carry_tool_calls_and_results_in_the_providers_shape():
    sdk, seen = stub(SimpleNamespace(stop_reason="end_turn", content=[text("ok")]))
    messages = [
        Message("user", "go"),
        Message("assistant", "", (ToolUse("tu_1", "cardholder_history", {}),)),
        Message("user", "", tool_results=(ToolResult("tu_1", "[]"), ToolResult("tu_2", "boom", True))),
    ]
    AnthropicClient("m", client=sdk).complete(system="S", messages=messages, tools=[SPEC])
    assert seen["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "go"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "tu_1", "name": "cardholder_history", "input": {}}]},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "[]", "is_error": False},
                {"type": "tool_result", "tool_use_id": "tu_2", "content": "boom", "is_error": True},
            ],
        },
    ]


def test_forcing_a_tool_sets_tool_choice():
    sdk, seen = stub(SimpleNamespace(stop_reason="end_turn", content=[text("")]))
    AnthropicClient("m", client=sdk).complete(system="S", messages=[Message("user", "x")], tools=[SPEC], force_tool="cardholder_history")
    assert seen["tool_choice"] == {"type": "tool", "name": "cardholder_history"}


def test_a_provider_error_becomes_llm_unavailable():
    # The SDK's HTTP library differs between versions, so the request is a plain stand-in.
    error = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="https://example.invalid"))
    sdk, _ = stub(error=error)
    with pytest.raises(LlmUnavailable):
        AnthropicClient("m", client=sdk).complete(system="S", messages=[Message("user", "x")], tools=[])


def _status_error(cls, status):
    response = SimpleNamespace(status_code=status, headers={}, request=SimpleNamespace(method="POST", url="https://example.invalid"))
    return cls("x", response=response, body=None)


@pytest.mark.parametrize(
    "error",
    [_status_error(anthropic.RateLimitError, 429), _status_error(anthropic.InternalServerError, 529)],
)
def test_rate_limits_and_server_errors_are_unavailable(error):
    sdk, _ = stub(error=error)
    with pytest.raises(LlmUnavailable):
        AnthropicClient("m", client=sdk).complete(system="S", messages=[Message("user", "x")], tools=[])


@pytest.mark.parametrize(
    "error",
    [
        _status_error(anthropic.AuthenticationError, 401),
        _status_error(anthropic.NotFoundError, 404),
        _status_error(anthropic.BadRequestError, 400),
    ],
)
def test_a_permanent_error_propagates_instead_of_looking_like_an_outage(error):
    sdk, _ = stub(error=error)
    with pytest.raises(anthropic.APIStatusError):
        AnthropicClient("m", client=sdk).complete(system="S", messages=[Message("user", "x")], tools=[])


def test_a_reply_cut_off_at_max_tokens_is_logged(caplog):
    sdk, _ = stub(SimpleNamespace(stop_reason="max_tokens", content=[text("")]))
    with caplog.at_level("WARNING"):
        AnthropicClient("m", client=sdk).complete(system="S", messages=[Message("user", "x")], tools=[])
    assert "max_tokens" in caplog.text
