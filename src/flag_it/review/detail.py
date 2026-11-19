"""What GET /decisions/{decision_id} returns: one run with everything a reviewer reads."""

from uuid import UUID

from flag_it.contracts.api import CitedRule, ReviewDetail
from flag_it.contracts.decide import AgentVerdict
from flag_it.contracts.rules import Rule, RuleSet
from flag_it.db import records
from flag_it.db.connection import Conn


def cited_rule(rule: Rule) -> CitedRule:
    return CitedRule(
        rule_id=rule.id,
        title=rule.title,
        text=rule.text,
        severity=rule.severity,
        source_section=rule.source.section,
        source_page=str(rule.source.page),
    )


def _rule_of_check(rules: RuleSet, check_id: str) -> str | None:
    try:
        return rules.check(check_id)[0].id
    except KeyError:  # the check is gone from today's rules: show the verdict without rule text
        return None


def review_detail(conn: Conn, decision_id: UUID, rules: RuleSet) -> ReviewDetail | None:
    try:
        run = records.load_decision_run(conn, decision_id)
    except records.NotFound:
        return None
    flags = records.load_flags(conn, decision_id)
    verdicts = tuple(
        AgentVerdict.model_validate(stored.model_dump(exclude={"decision_id"}))
        for stored in records.load_agent_verdicts(conn, decision_id)
    )
    history = records.load_decision_history(conn, run.txn_id)
    reviews = sorted(
        (review for past in history for review in records.load_review_outcomes(conn, past.decision_id)),
        key=lambda review: (review.created_at, str(review.review_id)),
    )
    cited = {flag.rule_id for flag in flags} | {_rule_of_check(rules, v.check_id) for v in verdicts}
    return ReviewDetail(
        run=run,
        snapshot=records.load_snapshot(conn, run.snapshot_id),
        flags=flags,
        agent_verdicts=verdicts,
        rules=tuple(cited_rule(rule) for rule in rules.rules if rule.id in cited),
        history=history,
        reviews=tuple(reviews),
    )
