"""Deadlines for checks with `timing` in the rules YAML: purchase+24h, cycle_end, cycle_signoff.

The Pcard accountant publishes a sign-off cutoff for each billing cycle; the guidelines don't fix
it (Pcard Guidelines, p. 14-15). So cycles and cutoffs come from a calendar file, not from code.
A transaction belongs to the cycle that contains its post date. A deadline in a cycle the
calendar doesn't list is unknown, and the check reports not_evaluated.
"""

import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Self

import yaml
from pydantic import AwareDatetime, model_validator

from flag_it.contracts.common import InputModel
from flag_it.contracts.transactions import NormalizedTransaction

_REPO_CALENDAR_PATH = Path(__file__).resolve().parents[4] / "policies" / "osu" / "billing_cycles.yaml"


def default_calendar_path() -> Path:
    """FLAG_IT_BILLING_CALENDAR_PATH if set, else the repo's policies/osu/billing_cycles.yaml."""
    return Path(os.environ.get("FLAG_IT_BILLING_CALENDAR_PATH", _REPO_CALENDAR_PATH))


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=timezone.utc)


class BillingCycle(InputModel):
    start: date
    end: date
    signoff_due: AwareDatetime  # the moment the sign-off cutoff passes

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError(f"cycle {self.start}: end is before start")
        if self.signoff_due < _midnight(self.end + timedelta(days=1)):
            raise ValueError(f"cycle {self.start}: sign-off is due before the cycle ends")
        return self


class BillingCalendar(InputModel):
    cycles: list[BillingCycle] = []

    @model_validator(mode="after")
    def _no_overlap(self) -> Self:
        ordered = sorted(self.cycles, key=lambda c: c.start)
        for earlier, later in zip(ordered, ordered[1:]):
            if later.start <= earlier.end:
                raise ValueError(f"cycles starting {earlier.start} and {later.start} overlap")
        return self

    def cycle_for(self, day: date) -> BillingCycle | None:
        return next((c for c in self.cycles if c.start <= day <= c.end), None)


def load_calendar(path: Path | None = None) -> BillingCalendar:
    data = yaml.safe_load((path or default_calendar_path()).read_text()) or {}
    return BillingCalendar.model_validate(data)


def due_at(due: str, txn: NormalizedTransaction, calendar: BillingCalendar) -> datetime | None:
    """When a check's deadline passes for this transaction, or None when the calendar can't say.

    purchase+24h: the time of purchase isn't known, so 24 hours after the end of the purchase day.
    cycle_end: the end of the last day of the transaction's billing cycle.
    cycle_signoff: that cycle's published sign-off cutoff.
    """
    if due == "purchase+24h":
        return _midnight(txn.transaction_date + timedelta(days=1)) + timedelta(hours=24)
    cycle = calendar.cycle_for(txn.post_date)
    if cycle is None:
        return None
    if due == "cycle_end":
        return _midnight(cycle.end + timedelta(days=1))
    if due == "cycle_signoff":
        return cycle.signoff_due
    raise ValueError(f"unknown deadline {due!r}")
