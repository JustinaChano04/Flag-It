"""Checks that look for a kind of line on the receipt (pattern line_item).

Each check reads up to three word lists from its rule's params in the rules YAML:
- `<name>_terms`: words that are certain evidence ("late fee"). A match fails the check.
- `<name>_review_terms`: ambiguous words ("interest"). A match only sends the run to be looked at.
- `<name>_except_terms`: phrases that cancel a match on that line ("special interest").

A line matches when its description contains a term as whole words, ignoring case and
punctuation. When nothing matches but some line has no description, the check can't tell.
"""

from flag_it.contracts.enums import LineType
from flag_it.decide.checks.base import (
    CheckContext,
    Finding,
    NeedsReview,
    NoFinding,
    Outcome,
    line_citation,
    matching_lines,
    mentions,
    policy,
    receipt_ref,
    unreadable_lines,
)

AMBIGUOUS = "ambiguous wording: the agent or a person should look"


def _no_line_with(name: str):
    """A checker for the word lists `<name>_terms`, `<name>_review_terms`, `<name>_except_terms`."""

    def checker(ctx: CheckContext) -> Outcome:
        receipt, excepted = ctx.receipt, ctx.optional_terms(f"{name}_except_terms")
        hits = matching_lines(receipt, ctx.terms(f"{name}_terms"), excepted)
        if hits:
            return Finding((*(line_citation(i, line, term) for i, line, term in hits), policy(ctx.rule.id)))
        maybe = matching_lines(receipt, ctx.optional_terms(f"{name}_review_terms"), excepted)
        if maybe:
            return NeedsReview((*(line_citation(i, line, term) for i, line, term in maybe), policy(ctx.rule.id, None, AMBIGUOUS)))
        return unreadable_lines(receipt) or NoFinding()

    checker.__name__ = f"no_line_with_{name}"
    return checker


no_alcohol_lines = _no_line_with("alcohol_line")  # OSU-PRH-01b
no_penalty_lines = _no_line_with("penalty_line")  # OSU-PRH-14a
no_postage_lines = _no_line_with("postage_line")  # OSU-PRH-19b
no_trade_in_lines = _no_line_with("trade_in_line")  # OSU-PRH-22a
premium_fare_lines = _no_line_with("premium_fare")  # OSU-TRV-04a (a gate: a finding means "found")
no_personal_folio_lines = _no_line_with("personal_folio")  # OSU-TRV-08a
no_ticket_lines = _no_line_with("ticket_line")  # OSU-TRV-17b


def insurance_is_physical_damage_only(ctx: CheckContext) -> Outcome:
    """OSU-PRH-12b: every insurance line is physical damage coverage."""
    receipt = ctx.receipt
    damage_terms = ctx.terms("physical_damage_terms")
    other = [
        (i, line, term)
        for i, line, term in matching_lines(receipt, ctx.terms("insurance_line_terms"))
        if mentions(line.description, damage_terms) is None
    ]
    if other:
        return Finding((
            *(line_citation(i, line, term) for i, line, term in other),
            policy(ctx.rule.id, None, "insurance other than physical damage coverage"),
        ))
    return unreadable_lines(receipt) or NoFinding()


def registration_and_lodging_together(ctx: CheckContext) -> Outcome:
    """OSU-TRV-09a: one charge doesn't contain both registration and lodging lines.
    A room line (line_type room) or a lodging term is certain; a word like "hotel" alone only
    sends the run to be looked at. "Meeting room" and similar never count as lodging."""
    receipt = ctx.receipt
    registration = matching_lines(receipt, ctx.terms("registration_terms"))
    if not registration:
        return unreadable_lines(receipt) or NoFinding()
    excepted = ctx.optional_terms("lodging_except_terms")
    rooms = {i for i, line in enumerate(receipt.line_items) if line.line_type is LineType.ROOM}
    lodging = sorted(rooms | {i for i, _, _ in matching_lines(receipt, ctx.terms("lodging_terms"), excepted)})
    cited = tuple(line_citation(i, line, term) for i, line, term in registration)
    if lodging:
        lines = receipt.line_items
        return Finding((
            *cited,
            *(receipt_ref(f"receipt.line_items[{i}]", lines[i].description, "lodging line") for i in lodging),
            policy(ctx.rule.id),
        ))
    maybe = matching_lines(receipt, ctx.optional_terms("lodging_review_terms"), excepted)
    if maybe:
        return NeedsReview((*cited, *(line_citation(i, line, term) for i, line, term in maybe), policy(ctx.rule.id, None, AMBIGUOUS)))
    return unreadable_lines(receipt) or NoFinding()
