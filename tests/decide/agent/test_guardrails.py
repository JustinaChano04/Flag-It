"""The guardrails: each condition sends the run to a person, and the fixtures agree with them."""

from uuid import uuid4

import pytest

from flag_it import fixtures
from flag_it.contracts.decide import AgentOutput, Citation
from flag_it.contracts.enums import DecidedBy, EvidenceKind, FlagResult, FlagSource, Route
from flag_it.contracts.rules import load_rules
from flag_it.decide.agent.guardrails import apply_guardrails, escalate, unresolved_citation
from flag_it.decide.agent.tools import ToolLedger

RULES = load_rules()
SETTINGS = RULES.agent_settings()
SNAPSHOT = fixtures.snapshot("cat_office_general_supplies")
PAYLOAD = SNAPSHOT.payload.model_dump(mode="json")
POLICY = {"kind": "policy", "ref": "OSU-PRH-09"}
FIELD = {"kind": "field", "ref": "transaction.amount"}


def output(*verdicts):
    return AgentOutput.model_validate({"verdicts": [
        {"check_id": c, "result": r, "confidence": conf, "evidence": list(ev)} for c, r, conf, *ev in verdicts
    ]})


def run_guardrails(out, ledger=None, snapshot=SNAPSHOT):
    return apply_guardrails(
        out, snapshot=snapshot, rules=RULES, ledger=ledger or ToolLedger(), settings=SETTINGS, decision_id=uuid4()
    )


def cite(kind, ref):
    return Citation(kind=EvidenceKind(kind), ref=ref)


def test_all_pass_is_agent_approve():
    result = run_guardrails(output(("OSU-GEN-06a", "pass", 0.9), ("OSU-PRH-09a", "pass", 0.9)))
    assert (result.route, result.decided_by, result.escalation_reasons, result.flags) == (
        Route.AGENT_APPROVE, DecidedBy.AGENT, (), ()
    )


def test_a_fail_is_agent_flag_and_becomes_a_flag_scored_with_the_confidence():
    result = run_guardrails(output(("OSU-GEN-06a", "pass", 0.9), ("OSU-PRH-09a", "fail", 0.8, POLICY, FIELD)))
    assert (result.route, result.decided_by) == (Route.AGENT_FLAG, DecidedBy.AGENT)
    [flag] = result.flags
    assert (flag.check_id, flag.rule_id, flag.result, flag.source, flag.score) == (
        "OSU-PRH-09a", "OSU-PRH-09", FlagResult.FAIL, FlagSource.LLM, 0.8
    )
    assert flag.severity == RULES.rule("OSU-PRH-09").severity and len(flag.evidence) == 2


def test_an_unsure_verdict_goes_to_a_person_with_an_unclear_flag():
    result = run_guardrails(output(("OSU-GEN-06a", "unsure", 0.9, FIELD)))
    assert (result.route, result.decided_by) == (Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS)
    assert result.escalation_reasons == ("unsure:OSU-GEN-06a",)
    assert [(f.check_id, f.result) for f in result.flags] == [("OSU-GEN-06a", FlagResult.UNCLEAR)]


def test_low_confidence_goes_to_a_person_even_on_a_pass():
    below = SETTINGS.min_confidence - 0.01
    result = run_guardrails(output(("OSU-GEN-06a", "pass", 0.9), ("OSU-PRH-09a", "pass", below)))
    assert result.route is Route.HUMAN_REVIEW and result.escalation_reasons == ("low_confidence:OSU-PRH-09a",)
    at = run_guardrails(output(("OSU-GEN-06a", "pass", SETTINGS.min_confidence)))
    assert at.route is Route.AGENT_APPROVE  # at the threshold is enough


def test_an_unresolved_citation_goes_to_a_person_and_makes_no_flag():
    bad = {"kind": "receipt", "ref": "receipt.line_items[4]"}  # the snapshot has no receipt
    result = run_guardrails(output(("OSU-PRH-09a", "fail", 0.9, POLICY, bad)))
    assert result.route is Route.HUMAN_REVIEW and result.escalation_reasons == ("citation_unresolved",)
    assert result.flags == ()


def test_several_conditions_each_give_their_reason_in_check_order():
    result = run_guardrails(output(
        ("OSU-PRH-09a", "unsure", 0.4, FIELD), ("OSU-GEN-06a", "pass", 0.3),
    ))
    assert result.escalation_reasons == ("low_confidence:OSU-GEN-06a", "unsure:OSU-PRH-09a", "low_confidence:OSU-PRH-09a")


def test_a_verdict_on_a_code_check_counts_for_the_route_but_makes_no_flag():
    out = output(("OSU-PRH-14a", "fail", 0.9, {"kind": "policy", "ref": "OSU-PRH-14"}, FIELD))
    result = run_guardrails(out)
    assert result.route is Route.AGENT_FLAG and result.flags == ()
    assert run_guardrails(output(("OSU-PRH-14a", "pass", 0.9))).route is Route.AGENT_APPROVE


def test_flag_ids_are_derived_from_the_run_and_the_check():
    out = output(("OSU-PRH-09a", "fail", 0.9, POLICY))
    decision_id = uuid4()
    kwargs = dict(snapshot=SNAPSHOT, rules=RULES, ledger=ToolLedger(), settings=SETTINGS)
    first = apply_guardrails(out, decision_id=decision_id, **kwargs).flags[0].flag_id
    assert first == apply_guardrails(out, decision_id=decision_id, **kwargs).flags[0].flag_id
    assert first != apply_guardrails(out, decision_id=uuid4(), **kwargs).flags[0].flag_id


@pytest.mark.parametrize(
    "kind, ref, resolves",
    [
        ("field", "transaction.amount", True),
        ("field", "transaction.nope", False),
        ("field", "anomaly.score", True),
        ("field", "raw.merchant_name", False),
        ("field", "transaction.amount.x", False),
        ("field", "transaction[0]", False),
        ("field", "receipt", False),  # this snapshot has no receipt
        ("receipt", "receipt.line_items[0]", False),
        ("policy", "OSU-PRH-09", True),
        ("policy", "OSU-PRH-09a", True),
        ("policy", "NOPE-99", False),
        ("tool_result", "tu_1", True),
        ("tool_result", "tu_9", False),
        ("history", "cardholder_history@2025-01-14T00:00:00+00:00", True),
        ("history", "cardholder_history@2001-01-01T00:00:00+00:00", False),
    ],
)
def test_which_citations_resolve(kind, ref, resolves):
    ledger = ToolLedger()
    ledger.record("tu_1", "cardholder_history", {}, "cardholder_history@2025-01-14T00:00:00+00:00")
    assert unresolved_citation(cite(kind, ref), PAYLOAD, RULES, ledger) is (not resolves)


def test_a_params_citation_resolves_when_some_rule_defines_the_param():
    name = next(name for rule in RULES.rules for name in rule.params)
    assert not unresolved_citation(cite("policy", f"params.{name}"), PAYLOAD, RULES, ToolLedger())
    assert unresolved_citation(cite("policy", "params.not_a_param"), PAYLOAD, RULES, ToolLedger())


def test_receipt_lines_resolve_when_the_receipt_has_them():
    snapshot = fixtures.snapshot("receipt_mismatch")
    payload = snapshot.payload.model_dump(mode="json")
    assert payload["receipt"] is not None and payload["receipt"]["line_items"], "pick a fixture with receipt lines"
    assert not unresolved_citation(cite("receipt", "receipt.line_items[0].description"), payload, RULES, ToolLedger())
    assert unresolved_citation(cite("receipt", "receipt.line_items[99]"), payload, RULES, ToolLedger())


def test_escalate_is_a_human_review_decided_by_the_guardrails():
    result = escalate("agent_failed")
    assert (result.route, result.decided_by, result.escalation_reasons, result.flags) == (
        Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS, ("agent_failed",), ()
    )


@pytest.mark.parametrize("name", sorted(set(fixtures.agent_outputs()) & set(fixtures.decision_runs())))
def test_the_fixtures_agree_with_the_guardrails(name):
    run = fixtures.decision_run(name)
    result = apply_guardrails(
        fixtures.agent_output(name), snapshot=fixtures.snapshot_for(run), rules=RULES, ledger=ToolLedger(),
        settings=SETTINGS, decision_id=run.decision_id,
    )
    assert (result.route, result.decided_by, result.escalation_reasons) == (run.route, run.decided_by, run.escalation_reasons)
    llm_flags = {(f.check_id, f.result) for f in fixtures.flags(name) if f.source is FlagSource.LLM}
    assert {(f.check_id, f.result) for f in result.flags} == llm_flags


def test_the_fixture_with_an_unresolved_citation_goes_to_a_person():
    result = run_guardrails(fixtures.agent_output("unresolved_citation"))
    assert result.route is Route.HUMAN_REVIEW and "citation_unresolved" in result.escalation_reasons
