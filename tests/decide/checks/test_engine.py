"""The engine's rules, tested on a small rule set with fake checkers so each rule shows on its own."""

from datetime import datetime, timezone
from uuid import UUID, uuid5

import pytest

from flag_it.contracts.enums import FlagResult, FlagSource, Severity
from flag_it.contracts.rules import RuleSet
from flag_it.decide.checks.base import CannotTell, Finding, NeedsReview, NoFinding, field
from flag_it.decide.checks.calendar import BillingCalendar
from flag_it.decide.checks.deployment import Deployment
from flag_it.decide.checks.engine import run_rule_checks
from tests.decide.checks.helpers import FIXTURE_CALENDAR, SIGNOFF, line, receipt, snapshot

RUN = UUID("00000000-0000-0000-0000-000000000001")
DEPLOYED = Deployment(frozenset({"transaction", "receipt"}))
FOUND = Finding((field("transaction.amount", "1"),))


def _rule(rule_id: str, severity: str, applies_to: list[str], *checks: dict, **extra) -> dict:
    return {
        "id": rule_id, "title": rule_id, "topic": "limits", "text": "Test rule.", "source": {"section": "S", "page": 1},
        "severity": severity, "applies_to": applies_to, "checks": list(checks), **extra,
    }


def _check(check_id: str, pattern: str, requires: list[str], **extra) -> dict:
    return {"id": check_id, "ask": "Test check.", "pattern": pattern, "method": "code", "requires": requires,
            "scope": "transaction", **extra}


RULES = RuleSet.model_validate({
    "policy": {"name": "Test", "version": "1", "source_file": "x.pdf", "scope": "test"},
    "categories": {"office_general_supplies": "Office", "lodging": "Lodging"},
    "rules_version": "1+test",
    "rules": [
        _rule("T-LIM-01", "prohibited", ["all"], _check("T-LIM-01a", "threshold", ["transaction"])),
        _rule("T-LOD-01", "prohibited", ["lodging"], _check("T-LOD-01a", "line_item", ["receipt"])),
        _rule("T-TAB-01", "prohibited", ["all"], _check("T-TAB-01a", "list_membership", ["transaction", "table:things"])),
        _rule("T-DOC-01", "documentation", ["all"],
              _check("T-DOC-01a", "document_presence", ["receipt"], timing={"due": "cycle_signoff"})),
        _rule("T-GAT-01", "prohibited", ["all"],
              _check("T-GAT-01a", "line_item", ["receipt"], role="gate"),
              _check("T-GAT-01b", "line_item", ["receipt"], when={"check": "T-GAT-01a", "result": True})),
        _rule("T-OFF-01", "prohibited", ["all"],
              _check("T-OFF-01a", "list_membership", ["transaction", "table:things"], role="gate"),
              _check("T-OFF-01b", "line_item", ["receipt"], when={"check": "T-OFF-01a", "result": True})),
        _rule("T-GDN-01", "guidance", ["all"], _check("T-GDN-01a", "threshold", ["transaction"])),
        _rule("T-UNS-01", "conditional", ["all"], _check("T-UNS-01a", "cross_reference", ["transaction", "receipt"])),
    ],
})


def run(*, checkers=None, receipt_=None, category=None, taken_at=None, calendar=FIXTURE_CALENDAR, unsupported=None):
    return run_rule_checks(
        snapshot(receipt=receipt_, category=category, taken_at=taken_at),
        RULES,
        decision_id=RUN,
        deployment=DEPLOYED,
        calendar=calendar,
        checkers=checkers or {},
        unsupported=unsupported or {},
    )


def results(outcome) -> dict[str, FlagResult]:
    return {f.check_id: f.result for f in outcome.flags}


def test_a_finding_becomes_a_hard_failure_flag_and_nothing_found_is_no_flag():
    outcome = run(checkers={"T-LIM-01a": lambda ctx: FOUND, "T-GDN-01a": lambda ctx: NoFinding()},
                  receipt_=receipt(line_items=[line("Pens", "4.00")]))
    flag = next(f for f in outcome.flags if f.check_id == "T-LIM-01a")
    assert (flag.result, flag.severity, flag.score, flag.source) == (
        FlagResult.FAIL, Severity.PROHIBITED, 1.0, FlagSource.CODE)
    assert (flag.rule_id, flag.decision_id, flag.flag_id) == ("T-LIM-01", RUN, uuid5(RUN, "T-LIM-01a"))
    assert "T-GDN-01a" not in results(outcome)
    assert outcome.hard_failure


def test_suggestive_evidence_is_unclear_never_hard_but_needs_review():
    maybe = NeedsReview((field("receipt.line_items[0]", "Interest"),))
    outcome = run(checkers={"T-LIM-01a": lambda ctx: maybe}, receipt_=receipt(line_items=[line("Pens", "4.00")]))
    assert results(outcome)["T-LIM-01a"] is FlagResult.UNCLEAR
    assert outcome.needs_review and not outcome.hard_failure


def test_a_mismatched_receipt_is_only_judged_by_cross_reference_checks():
    mismatched = receipt(match_status="mismatch", line_items=[line("Pens", "4.00")])
    outcome = run(checkers={"T-GAT-01a": lambda ctx: FOUND, "T-GAT-01b": lambda ctx: FOUND,
                            "T-UNS-01a": lambda ctx: FOUND}, receipt_=mismatched)
    assert outcome.gates["T-GAT-01a"] is None  # a line check: held back
    assert results(outcome)["T-GAT-01b"] is FlagResult.NOT_EVALUATED
    assert results(outcome)["T-UNS-01a"] is FlagResult.FAIL  # cross_reference: still runs


def test_a_checker_that_raises_is_not_evaluated_logged_and_the_rest_still_run(caplog):
    def broken(ctx):
        raise ZeroDivisionError("boom")

    outcome = run(checkers={"T-LIM-01a": broken, "T-GDN-01a": lambda ctx: FOUND})
    flag = next(f for f in outcome.flags if f.check_id == "T-LIM-01a")
    assert flag.result is FlagResult.NOT_EVALUATED and "ZeroDivisionError" in flag.evidence[0].note
    assert results(outcome)["T-GDN-01a"] is FlagResult.FAIL
    assert "T-LIM-01a" in caplog.text


def test_a_guidance_failure_is_recorded_but_not_hard():
    outcome = run(checkers={"T-GDN-01a": lambda ctx: FOUND}, receipt_=receipt(line_items=[line("Pens", "4.00")]))
    assert results(outcome)["T-GDN-01a"] is FlagResult.FAIL
    assert not outcome.hard_failure


def test_only_checks_for_the_category_run():
    assert "T-LOD-01a" not in results(run())
    assert results(run(category="lodging"))["T-LOD-01a"] is FlagResult.NOT_EVALUATED


def test_checks_needing_an_input_the_deployment_lacks_are_skipped_with_their_dependents():
    outcome = run()
    assert outcome.skipped == ("T-TAB-01a", "T-OFF-01a", "T-OFF-01b")
    assert not {"T-TAB-01a", "T-OFF-01a", "T-OFF-01b"} & set(results(outcome))


def test_a_missing_receipt_is_not_evaluated_and_names_the_input():
    flag = next(f for f in run(category="lodging").flags if f.check_id == "T-LOD-01a")
    assert flag.evidence[0].note == "missing input: receipt"


def test_a_missing_document_is_pending_until_its_deadline_then_fails():
    before = run(taken_at=datetime(2025, 3, 3, tzinfo=timezone.utc))
    pending = next(f for f in before.flags if f.check_id == "T-DOC-01a")
    assert (pending.result, pending.due_at) == (FlagResult.PENDING, SIGNOFF)
    assert not before.hard_failure
    after = run(taken_at=datetime(2025, 4, 11, tzinfo=timezone.utc))
    assert results(after)["T-DOC-01a"] is FlagResult.FAIL and after.hard_failure


def test_at_the_deadline_itself_the_document_is_late():
    assert results(run(taken_at=SIGNOFF))["T-DOC-01a"] is FlagResult.FAIL


def test_an_unknown_deadline_is_not_evaluated():
    flag = next(f for f in run(calendar=BillingCalendar()).flags if f.check_id == "T-DOC-01a")
    assert flag.result is FlagResult.NOT_EVALUATED
    assert flag.evidence[-1].ref == "billing_cycles"


def test_a_gate_runs_its_dependents_only_when_it_finds_something_and_is_never_a_flag():
    with_lines = receipt(line_items=[line("Pens", "4.00")])
    found = run(checkers={"T-GAT-01a": lambda ctx: FOUND, "T-GAT-01b": lambda ctx: FOUND}, receipt_=with_lines)
    assert found.gates["T-GAT-01a"] is True
    assert results(found)["T-GAT-01b"] is FlagResult.FAIL and "T-GAT-01a" not in results(found)
    clear = run(checkers={"T-GAT-01a": lambda ctx: NoFinding(), "T-GAT-01b": lambda ctx: FOUND}, receipt_=with_lines)
    assert clear.gates["T-GAT-01a"] is False and "T-GAT-01b" not in results(clear)


def test_a_gate_that_cannot_tell_leaves_its_dependents_not_evaluated():
    unsure = CannotTell((field("receipt.line_items", None, "blank"),))
    outcome = run(checkers={"T-GAT-01a": lambda ctx: unsure, "T-GAT-01b": lambda ctx: FOUND},
                  receipt_=receipt(line_items=[line(None)]))
    assert outcome.gates["T-GAT-01a"] is None
    assert results(outcome)["T-GAT-01b"] is FlagResult.NOT_EVALUATED


def test_unsupported_and_unimplemented_checks_are_not_evaluated_with_a_reason():
    outcome = run(unsupported={"T-UNS-01a": "no such field"}, receipt_=receipt(line_items=[line("Pens", "4.00")]))
    by_id = {f.check_id: f for f in outcome.flags}
    assert by_id["T-UNS-01a"].result is FlagResult.NOT_EVALUATED
    assert "no such field" in by_id["T-UNS-01a"].evidence[0].note
    assert "no checker" in by_id["T-LIM-01a"].evidence[0].note


def test_the_same_run_gives_the_same_flags():
    assert run(checkers={"T-LIM-01a": lambda ctx: FOUND}) == run(checkers={"T-LIM-01a": lambda ctx: FOUND})


@pytest.mark.parametrize("checker", [lambda ctx: FOUND, lambda ctx: NoFinding()])
def test_flags_follow_the_rules_file_order(checker):
    ids = [f.check_id for f in run(checkers={"T-LIM-01a": checker}).flags]
    assert ids == sorted(ids, key=["T-LIM-01a", "T-DOC-01a", "T-GAT-01b", "T-GDN-01a", "T-UNS-01a"].index)
