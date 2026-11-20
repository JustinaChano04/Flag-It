from flag_it.contracts.rules import load_rules
from flag_it.decide.checks.calendar import BillingCalendar, load_calendar
from flag_it.decide.checks.deployment import Deployment, load_deployment
from flag_it.pipeline.versions import stamp


def test_stamp_is_the_rules_version_plus_eight_hex_chars_and_is_stable():
    rules, deployment, calendar = load_rules(), load_deployment(), load_calendar()
    one = stamp(rules, deployment, calendar)
    assert one == stamp(rules, deployment, calendar)
    prefix, _, digest = one.rpartition("+")
    assert prefix == rules.rules_version and len(digest) == 8 and int(digest, 16) >= 0


def test_stamp_changes_with_the_deployment_inputs():
    rules, calendar = load_rules(), load_calendar()
    base = load_deployment()
    other = Deployment(base.inputs | {"an_extra_input"})
    assert stamp(rules, base, calendar) != stamp(rules, other, calendar)


def test_stamp_changes_with_the_calendar():
    rules, deployment = load_rules(), load_deployment()
    cycle = {"start": "2026-05-01", "end": "2026-05-31", "signoff_due": "2026-06-10T00:00:00+00:00"}
    other = BillingCalendar.model_validate({"cycles": [cycle]})
    assert stamp(rules, deployment, BillingCalendar(cycles=[])) != stamp(rules, deployment, other)
