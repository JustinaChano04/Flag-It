"""The prompt sends a minimized view, fences untrusted text, and forces the answer into the contract's schema."""

import json

import pytest

from flag_it import fixtures
from flag_it.contracts import examples as ex
from flag_it.contracts.rules import load_rules
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.decide.agent.prompt import (
    CLOSE,
    OPEN,
    SUBMIT,
    SYSTEM_PROMPT,
    agent_view,
    build_user_message,
    fence,
    pseudonym,
    submit_spec,
)
from tests.decide.agent.injections import ATTACKS

RULES = load_rules()


def snapshot_with(**over):
    """The example transaction with a receipt, with fields overridden."""
    receipt = ex.receipt(**over.pop("receipt", {}))
    return CombinedExpenseSnapshot.build(ex.combined(receipt=receipt, **over))


def inner(fenced: str) -> str:
    assert fenced.startswith(OPEN) and fenced.endswith(CLOSE)
    return fenced[len(OPEN) : -len(CLOSE)]


def test_the_answer_schema_is_the_contracts_agent_output():
    spec = submit_spec()
    assert spec.name == SUBMIT == "submit_verdicts"
    assert "verdicts" in spec.parameters["properties"]


@pytest.mark.parametrize("attack", ATTACKS)
def test_untrusted_text_is_fenced_and_cannot_close_its_own_fence(attack):
    assert "untrusted>" not in inner(fence(attack)).lower()
    snap = snapshot_with(receipt={"line_items": [{"description": attack, "amount": "5.00"}]})
    view = agent_view(snap)
    assert "untrusted>" not in inner(view["receipt"]["line_items"][0]["description"]).lower()
    assert view["receipt"]["line_items"][0]["description"].startswith(OPEN)


def test_merchant_purpose_and_receipt_merchant_are_fenced():
    snap = snapshot_with(receipt={"merchant": "Bob's"})
    view = agent_view(snap)
    assert view["transaction"]["merchant_norm"].startswith(OPEN)
    assert view["receipt"]["merchant"].startswith(OPEN)


def test_the_view_drops_ids_and_hides_the_cardholders_name():
    snap = snapshot_with()
    text = json.dumps(agent_view(snap))
    assert "SMITH" not in text
    assert str(snap.txn_id) not in text and str(snap.payload.transaction.raw_id) not in text
    assert agent_view(snap)["transaction"]["cardholder_id"] == pseudonym("01000|SMITH|J")
    assert pseudonym("01000|SMITH|J") == pseudonym("01000|SMITH|J") != pseudonym("01000|JONES|K")


def test_the_view_keeps_the_paths_a_citation_will_use():
    view = agent_view(snapshot_with(receipt={"line_items": [{"description": "Pens", "amount": "5.00"}]}))
    assert "amount" in view["transaction"] and "line_items" in view["receipt"]
    assert {"status", "score"} <= set(view["anomaly"]) and "category" in view["category"]


def test_the_view_has_no_receipt_when_there_is_none():
    assert agent_view(fixtures.snapshot("cat_office_general_supplies"))["receipt"] is None


def test_the_user_message_lists_each_check_with_its_criteria():
    snap = fixtures.snapshot("cat_office_general_supplies")
    message = json.loads(build_user_message(snap, RULES, ("OSU-GEN-06a",), ()))
    [item] = message["checks"]
    rule, check = RULES.check("OSU-GEN-06a")
    assert item["check_id"] == "OSU-GEN-06a" and item["rule_id"] == rule.id and item["ask"] == check.ask
    assert item["criteria"]["violation"] == check.decision.violation
    assert message["transaction_view"]["transaction"]["merchant_norm"].startswith(OPEN)


def test_an_unclear_code_flag_is_shown_with_its_evidence_fenced():
    snap = fixtures.snapshot("cat_office_general_supplies")
    flag = ex.flag(
        rule_id="OSU-PRH-14", check_id="OSU-PRH-14a", result="unclear", source="code", score=1.0,
        evidence=[{"kind": "receipt", "ref": "receipt.line_items[0]", "value": "Interest - Nov", "note": "ambiguous wording"}],
    )
    message = json.loads(build_user_message(snap, RULES, ("OSU-PRH-14a",), (flag,)))
    [item] = message["checks"]
    assert item["check_id"] == "OSU-PRH-14a" and "why_unclear" in item
    [citation] = item["why_unclear"]
    assert citation["ref"] == "receipt.line_items[0]" and citation["value"].startswith(OPEN)


def test_the_system_prompt_states_the_standing_rules():
    for needle in ("submit_verdicts", "untrusted", "unsure", "policy citation", "anomaly score"):
        assert needle in SYSTEM_PROMPT
