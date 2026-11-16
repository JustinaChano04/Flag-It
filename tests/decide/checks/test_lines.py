"""Line-item checks: certain words fail, ambiguous words ask for review, innocent lines pass."""

import pytest

from flag_it.decide.checks import lines
from flag_it.decide.checks.base import CannotTell, Finding, NeedsReview, NoFinding
from tests.decide.checks.helpers import context, line, receipt

CASES = [
    ("OSU-PRH-01b", lines.no_alcohol_lines, "House wine, glass", "Caesar salad"),
    ("OSU-PRH-14a", lines.no_penalty_lines, "Late fee", "Annual dues"),
    ("OSU-PRH-19b", lines.no_postage_lines, "Forever stamps, book of 20", "Rubber stamp, self-inking"),
    ("OSU-PRH-22a", lines.no_trade_in_lines, "Trade-in credit, old laptop", "Laptop"),
    ("OSU-TRV-04a", lines.premium_fare_lines, "Seat upgrade", "Economy fare"),
    ("OSU-TRV-08a", lines.no_personal_folio_lines, "Minibar", "Room, 1 night"),
    ("OSU-TRV-17b", lines.no_ticket_lines, "Parking citation", "Garage, 3 hours"),
]


@pytest.mark.parametrize(("check_id", "checker", "bad", "good"), CASES)
def test_a_matching_line_is_found_and_cited(rules, check_id, checker, bad, good):
    outcome = checker(context(rules, check_id, receipt=receipt(line_items=[line(good, "10.00"), line(bad, "5.00")])))
    assert isinstance(outcome, Finding)
    assert outcome.evidence[0].ref == "receipt.line_items[1]" and outcome.evidence[0].value == bad
    assert outcome.evidence[-1].ref == rules.check(check_id)[0].id


@pytest.mark.parametrize(("check_id", "checker", "bad", "good"), CASES)
def test_ordinary_lines_find_nothing(rules, check_id, checker, bad, good):
    assert isinstance(checker(context(rules, check_id, receipt=receipt(line_items=[line(good, "10.00")]))), NoFinding)


@pytest.mark.parametrize(("check_id", "checker", "bad", "good"), CASES)
def test_a_line_without_a_description_cannot_be_ruled_out(rules, check_id, checker, bad, good):
    r = receipt(line_items=[line(good, "10.00"), line(None, "5.00")])
    assert isinstance(checker(context(rules, check_id, receipt=r)), CannotTell)


# Lines that are fine but share words with a rule. A hard failure here would flag an innocent
# purchase outright, so every word list gets cases. Add one whenever a reviewer overrules a flag.
INNOCENT = [
    ("OSU-PRH-01b", lines.no_alcohol_lines, "Root beer float"),
    ("OSU-PRH-01b", lines.no_alcohol_lines, "Red wine vinegar"),
    ("OSU-PRH-01b", lines.no_alcohol_lines, "Non-alcoholic beer"),
    ("OSU-PRH-14a", lines.no_penalty_lines, "Special Interest Group dues"),
    ("OSU-PRH-19b", lines.no_postage_lines, "Rubber stamp, self-inking"),
    ("OSU-PRH-22a", lines.no_trade_in_lines, "Trade show booth"),
    ("OSU-TRV-04a", lines.premium_fare_lines, "Checked bag"),
    ("OSU-TRV-08a", lines.no_personal_folio_lines, "Resort fee"),
    ("OSU-TRV-08a", lines.no_personal_folio_lines, "Safety deposit"),
    ("OSU-TRV-17b", lines.no_ticket_lines, "Parking, level 2"),
]

# Lines that might break the rule. They must ask for review, never fail outright.
AMBIGUOUS = [
    ("OSU-PRH-14a", lines.no_penalty_lines, "Interest, 30 days"),
    ("OSU-TRV-04a", lines.premium_fare_lines, "Priority"),
    ("OSU-TRV-08a", lines.no_personal_folio_lines, "Bar"),
    ("OSU-TRV-08a", lines.no_personal_folio_lines, "Restaurant charge"),
    ("OSU-TRV-17b", lines.no_ticket_lines, "Violation notice"),
]


@pytest.mark.parametrize(("check_id", "checker", "description"), INNOCENT)
def test_innocent_lines_that_share_a_word_find_nothing(rules, check_id, checker, description):
    r = receipt(line_items=[line(description, "10.00")])
    assert isinstance(checker(context(rules, check_id, receipt=r)), NoFinding)


@pytest.mark.parametrize(("check_id", "checker", "description"), AMBIGUOUS)
def test_ambiguous_lines_ask_for_review_and_cite_the_line(rules, check_id, checker, description):
    outcome = checker(context(rules, check_id, receipt=receipt(line_items=[line(description, "10.00")])))
    assert isinstance(outcome, NeedsReview)
    assert outcome.evidence[0].ref == "receipt.line_items[0]"


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Loss damage waiver (LDW)", NoFinding),
        ("Physical damage coverage", NoFinding),
        ("Supplemental liability insurance", Finding),
        ("Personal accident insurance (PAI)", Finding),
    ],
)
def test_rental_insurance_must_be_physical_damage_only(rules, description, expected):
    r = receipt(line_items=[line("Midsize car, 3 days", "150.00"), line(description, "30.00")])
    assert isinstance(lines.insurance_is_physical_damage_only(context(rules, "OSU-PRH-12b", receipt=r)), expected)


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([line("Conference registration", "300.00"), line("Room, 2 nights", "258.00", "room")], Finding),
        ([line("Conference registration", "300.00"), line("Hotel room, 2 nights", "258.00")], Finding),
        ([line("Conference registration", "300.00"), line("Hotel package", "258.00")], NeedsReview),
        ([line("Conference registration", "300.00"), line("Meeting room rental", "120.00")], NoFinding),
        ([line("Conference registration", "300.00")], NoFinding),
        ([line("Room, 2 nights", "258.00", "room")], NoFinding),
    ],
)
def test_registration_and_lodging_on_one_charge(rules, items, expected):
    ctx = context(rules, "OSU-TRV-09a", receipt=receipt(line_items=items))
    assert isinstance(lines.registration_and_lodging_together(ctx), expected)
