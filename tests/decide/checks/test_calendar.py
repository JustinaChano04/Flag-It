"""Deadlines come from the transaction's dates and the billing calendar."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from flag_it import fixtures
from flag_it.decide.checks.calendar import BillingCalendar, due_at, load_calendar
from tests.decide.checks.helpers import FIXTURE_CALENDAR, SIGNOFF

TXN = fixtures.snapshot("cat_office_general_supplies").payload.transaction  # bought 2025-02-27, posted 02-28


def test_the_cycle_is_found_by_post_date():
    cycle = FIXTURE_CALENDAR.cycle_for(date(2025, 2, 28))
    assert cycle is not None and cycle.end == date(2025, 3, 20)
    assert FIXTURE_CALENDAR.cycle_for(date(2025, 3, 21)) is None


def test_each_kind_of_deadline():
    assert due_at("purchase+24h", TXN, FIXTURE_CALENDAR) == datetime(2025, 3, 1, tzinfo=timezone.utc)
    assert due_at("cycle_end", TXN, FIXTURE_CALENDAR) == datetime(2025, 3, 21, tzinfo=timezone.utc)
    assert due_at("cycle_signoff", TXN, FIXTURE_CALENDAR) == SIGNOFF


def test_a_cycle_the_calendar_lacks_has_no_deadline():
    assert due_at("cycle_signoff", TXN, BillingCalendar()) is None
    assert due_at("cycle_end", TXN, BillingCalendar()) is None
    assert due_at("purchase+24h", TXN, BillingCalendar()) is not None  # needs no calendar


def test_unknown_deadline_kinds_are_refused():
    with pytest.raises(ValueError):
        due_at("next_tuesday", TXN, FIXTURE_CALENDAR)


@pytest.mark.parametrize(
    "cycles",
    [
        [{"start": "2025-03-20", "end": "2025-02-21", "signoff_due": "2025-04-10T23:59:00Z"}],  # backwards
        [{"start": "2025-02-21", "end": "2025-03-20", "signoff_due": "2025-03-20T12:00:00Z"}],  # due before the end
        [{"start": "2025-02-21", "end": "2025-03-20", "signoff_due": "2025-04-10T23:59:00"}],  # no UTC offset
        [
            {"start": "2025-02-21", "end": "2025-03-20", "signoff_due": "2025-04-10T23:59:00Z"},
            {"start": "2025-03-20", "end": "2025-04-20", "signoff_due": "2025-05-10T23:59:00Z"},  # overlaps
        ],
    ],
)
def test_bad_calendars_are_refused(cycles):
    with pytest.raises(ValidationError):
        BillingCalendar.model_validate({"cycles": cycles})


def test_the_shipped_calendar_loads():
    assert isinstance(load_calendar(), BillingCalendar)


def test_the_calendar_path_can_be_moved(monkeypatch, tmp_path):
    path = tmp_path / "cycles.yaml"
    path.write_text("cycles:\n  - {start: 2025-02-21, end: 2025-03-20, signoff_due: '2025-04-10T23:59:00Z'}\n")
    monkeypatch.setenv("FLAG_IT_BILLING_CALENDAR_PATH", str(path))
    assert load_calendar().cycle_for(date(2025, 3, 1)) is not None
