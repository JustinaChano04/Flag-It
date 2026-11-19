"""review_detail gathers one run with everything a reviewer reads."""

from uuid import uuid4

from flag_it import fixtures
from flag_it.contracts.rules import load_rules
from flag_it.fixtures.seed import seed
from flag_it.review.detail import review_detail

RULES = load_rules()


def test_the_detail_holds_the_run_its_snapshot_flags_and_cited_rules(conn):
    seed(conn)
    run = fixtures.decision_run("flag_over_limit")
    detail = review_detail(conn, run.decision_id, RULES)
    assert detail.run == run
    assert detail.snapshot == fixtures.snapshot_for(run)
    assert [f.check_id for f in detail.flags] == ["OSU-LIM-01a"]
    rule = RULES.rule("OSU-LIM-01")
    assert [(r.rule_id, r.title, r.text) for r in detail.rules] == [(rule.id, rule.title, rule.text)]
    assert detail.history == (run,)


def test_agent_verdicts_and_the_rules_they_cite_are_included(conn):
    seed(conn)
    run = fixtures.decision_run("guardrails_unsure")
    detail = review_detail(conn, run.decision_id, RULES)
    verdicts = fixtures.agent_output("guardrails_unsure").verdicts
    assert {v.check_id for v in detail.agent_verdicts} == {v.check_id for v in verdicts}
    cited = {RULES.check(v.check_id)[0].id for v in verdicts} | {f.rule_id for f in detail.flags}
    assert {r.rule_id for r in detail.rules} == cited


def test_a_rerun_shows_its_chain_and_the_earlier_review(conn):
    seed(conn)
    first, second = fixtures.decision_run("lodging_stay_1"), fixtures.decision_run("lodging_stay_2")
    detail = review_detail(conn, second.decision_id, RULES)
    assert detail.history == (second, first)
    assert [r.decision_id for r in detail.reviews] == [first.decision_id, second.decision_id]


def test_an_unknown_run_has_no_detail(conn):
    assert review_detail(conn, uuid4(), RULES) is None
