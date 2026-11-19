"""The loop: tools, the call cap, the forced answer, and one retry for an invalid answer."""

import pytest

from flag_it.contracts.rules import AgentSettings
from flag_it.decide.agent.llm import LlmUnavailable, ToolResult, ToolSpec
from flag_it.decide.agent.loop import InvalidOutput, run_agent
from tests.decide.agent.fakes import ScriptedClient, reply, submit, use, verdict

SETTINGS = AgentSettings(min_confidence=0.5, max_tool_calls=2)
CHECKS = ("OSU-GEN-06a", "OSU-PRH-09a")
GOOD = submit(verdict("OSU-GEN-06a", "pass", 0.9), verdict("OSU-PRH-09a", "pass", 0.9))


class FakeToolBox:
    def __init__(self):
        self.called = []

    def specs(self):
        return (ToolSpec("cardholder_history", "d", {"type": "object"}),)

    def call(self, u):
        self.called.append(u.id)
        return ToolResult(u.id, "{}")


def run(client, toolbox=None):
    return run_agent(
        client, system="S", user_message="U", toolbox=toolbox or FakeToolBox(), settings=SETTINGS, check_ids=CHECKS
    )


def test_a_direct_answer_is_returned():
    client = ScriptedClient(GOOD)
    out = run(client)
    assert {v.check_id for v in out.verdicts} == set(CHECKS)
    assert client.calls[0]["tools"] == ("cardholder_history", "submit_verdicts") and client.calls[0]["force_tool"] is None


def test_tool_results_are_sent_back_before_the_answer():
    box = FakeToolBox()
    client = ScriptedClient(reply(use("t1", "cardholder_history")), GOOD)
    run(client, box)
    assert box.called == ["t1"]
    last = client.calls[1]["messages"][-1]
    assert last.role == "user" and [r.tool_use_id for r in last.tool_results] == ["t1"]


def test_at_the_call_cap_the_model_is_forced_to_answer():
    box = FakeToolBox()
    client = ScriptedClient(
        reply(use("t1", "cardholder_history")), reply(use("t2", "cardholder_history")), GOOD
    )
    run(client, box)
    assert [c["force_tool"] for c in client.calls] == [None, None, "submit_verdicts"]
    assert box.called == ["t1", "t2"]


def test_calls_past_the_cap_in_one_reply_are_refused_not_run():
    box = FakeToolBox()
    three = reply(use("t1", "cardholder_history"), use("t2", "cardholder_history"), use("t3", "cardholder_history"))
    client = ScriptedClient(three, GOOD)
    run(client, box)
    assert box.called == ["t1", "t2"]
    refused = client.calls[1]["messages"][-1].tool_results[-1]
    assert refused.tool_use_id == "t3" and refused.is_error


def test_a_bad_answer_gets_one_retry_with_the_problem_explained():
    client = ScriptedClient(submit(verdict("OSU-GEN-06a", "fail", 0.9)), GOOD)  # a fail with no citation
    out = run(client)
    assert len(out.verdicts) == 2
    error = client.calls[1]["messages"][-1].tool_results[0]
    assert error.tool_use_id == "tu_submit" and error.is_error and "citation" in error.content


def test_an_answer_that_misses_or_adds_a_check_is_a_bad_answer():
    missing = submit(verdict("OSU-GEN-06a", "pass", 0.9))
    extra = submit(verdict("OSU-GEN-06a", "pass", 0.9), verdict("OSU-PRH-09a", "pass", 0.9), verdict("OSU-PRH-14a", "pass", 0.9))
    for bad in (missing, extra):
        client = ScriptedClient(bad, GOOD)
        assert len(run(client).verdicts) == 2
        assert "OSU" in client.calls[1]["messages"][-1].tool_results[0].content


def test_two_bad_answers_raise_invalid_output():
    with pytest.raises(InvalidOutput):
        run(ScriptedClient(submit(), submit()))


def test_prose_instead_of_an_answer_gets_one_reminder():
    client = ScriptedClient(reply(text="I think it is fine."), GOOD)
    run(client)
    assert client.calls[1]["messages"][-1].role == "user" and "submit_verdicts" in client.calls[1]["messages"][-1].text
    with pytest.raises(InvalidOutput):
        run(ScriptedClient(reply(text="fine"), reply(text="really fine")))


def test_an_empty_reply_is_recorded_with_text_so_the_next_request_is_valid():
    client = ScriptedClient(reply(), GOOD)
    run(client)
    assistant = [m for m in client.calls[1]["messages"] if m.role == "assistant"][0]
    assert assistant.text and not assistant.tool_uses


def test_the_retry_is_shared_between_prose_and_invalid_answers():
    with pytest.raises(InvalidOutput):
        run(ScriptedClient(reply(text="hm"), submit()))


def test_a_model_failure_propagates():
    with pytest.raises(LlmUnavailable):
        run(ScriptedClient(LlmUnavailable("down")))
