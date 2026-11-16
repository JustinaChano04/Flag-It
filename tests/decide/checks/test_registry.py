"""The registry covers every check the deployment can run, and the real checks agree with the fixtures."""

import pytest

from flag_it import fixtures
from flag_it.contracts.enums import CheckMethod, DecidedBy, FlagResult, FlagSource
from flag_it.decide.checks.base import CheckContext
from flag_it.decide.checks.deployment import load_deployment
from flag_it.decide.checks.engine import run_rule_checks
from flag_it.decide.checks.registry import CHECKERS, UNSUPPORTED
from tests.decide.checks.helpers import FIXTURE_CALENDAR, line, receipt, snapshot

AGENT_OR_SCREENER = {DecidedBy.SCREENER, DecidedBy.AGENT, DecidedBy.GUARDRAILS}


def _code_checks(rules):
    return [(rule, check) for rule in rules.rules if rule.status == "active"
            for check in rule.checks if check.method is CheckMethod.CODE]


def test_every_deployable_check_is_implemented_or_explained(rules):
    deployment = load_deployment()
    gated_off = {c.id for _, c in _code_checks(rules)
                 if c.when and any(deployment.missing(rules.check(ref)[1]) for ref in c.when.referenced())}
    runnable = {c.id for _, c in _code_checks(rules) if not deployment.missing(c)} - gated_off
    assert runnable == set(CHECKERS) | set(UNSUPPORTED)
    assert not set(CHECKERS) & set(UNSUPPORTED)


def test_registry_ids_are_real_code_checks(rules):
    for check_id in [*CHECKERS, *UNSUPPORTED]:
        _, check = rules.check(check_id)
        assert check.method is CheckMethod.CODE


@pytest.mark.parametrize("check_id", sorted(CHECKERS))
def test_every_checker_finds_its_params(rules, check_id):
    rule, check = rules.check(check_id)
    full = receipt(receipt_date="2025-02-27", merchant="Shop", subtotal="100.00", tip="5.00", total="105.00",
                   line_items=[line("Item", "100.00"), line("Tip", "5.00", "tip")])
    snap = snapshot(receipt=full)
    CHECKERS[check_id](CheckContext(snap.payload, rule, check))  # raises if a param is missing


def _engine(rules, snap, decision_id):
    return run_rule_checks(snap, rules, decision_id=decision_id, deployment=load_deployment(), calendar=FIXTURE_CALENDAR)


def test_every_fixture_snapshot_runs(rules):
    for name, snap in fixtures.snapshots().items():
        outcome = _engine(rules, snap, snap.snapshot_id)
        assert all(f.txn_id == snap.txn_id for f in outcome.flags), name


def test_fixture_code_flags_match_what_the_checks_find(rules):
    # Both directions, for implemented checks: every fixture flag is found, and no fail is invented.
    for name, run in fixtures.decision_runs().items():
        found = {(f.check_id, f.result) for f in _engine(rules, fixtures.snapshot_for(run), run.decision_id).flags}
        expected = {(f.check_id, f.result) for f in fixtures.flags(name)
                    if f.source is FlagSource.CODE and f.check_id in CHECKERS}
        assert expected <= found, name
        invented = {(c, r) for c, r in found if c in CHECKERS and r is FlagResult.FAIL} - expected
        assert not invented, (name, invented)


def test_runs_the_agent_or_screener_decided_have_no_hard_failure(rules):
    # A run that reached the screener or the agent must not break a code rule. Once the reference
    # tables are deployed, a mistake like plan 03's gift-card fixture (OSU-PRH-10a) fails here.
    for name, run in fixtures.decision_runs().items():
        if run.decided_by in AGENT_OR_SCREENER or run.route is None:
            assert not _engine(rules, fixtures.snapshot_for(run), run.decision_id).hard_failure, name
