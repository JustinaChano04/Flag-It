"""Checks on amounts and on the receipt as a document: limits, percentages, totals, completeness.

Limits, tolerances, and percentages come from the rule's params. Amounts are Decimal throughout,
and a percentage is compared exactly: it is rounded only for the note a person reads.
"""

from decimal import Decimal

from flag_it.contracts.enums import LineType, MatchStatus
from flag_it.decide.checks.base import (
    CannotTell,
    CheckContext,
    Finding,
    NeedsReview,
    NoFinding,
    Outcome,
    blank,
    field,
    line_citation,
    matching_lines,
    policy,
    receipt_ref,
)

CENT = Decimal("0.01")


def _param_decimal(ctx: CheckContext, name: str) -> Decimal:
    return Decimal(str(ctx.rule.param(name)))


def _percent(part: Decimal, whole: Decimal) -> Decimal:
    """For notes only. Compare with _over_share, which doesn't round."""
    return (part / whole * 100).quantize(CENT)


def _over_share(part: Decimal, whole: Decimal, limit_pct: Decimal) -> bool:
    """part is more than limit_pct percent of whole, exactly: 4.002% is over 4%."""
    return part * 100 > limit_pct * whole


def single_transaction_limit(ctx: CheckContext) -> Outcome:
    """OSU-LIM-01a: the charge is at most max_single_transaction."""
    limit = _param_decimal(ctx, "max_single_transaction").quantize(CENT)
    amount = ctx.txn.amount
    if amount <= limit:
        return NoFinding()
    return Finding((
        field("transaction.amount", str(amount)),
        policy("params.max_single_transaction", str(limit), f"Over by {amount - limit}"),
    ))


def itemized_receipt(ctx: CheckContext) -> Outcome:
    """OSU-GEN-04a, when a receipt exists: it shows a date, merchant, priced line items and a total.
    A missing receipt is handled by the engine (document_presence). A part the reader left blank
    can't fail the check: the receipt may show it and the reader missed it."""
    receipt = ctx.receipt
    blanks = [
        ref
        for ref, value in (
            ("receipt.receipt_date", receipt.receipt_date),
            ("receipt.merchant", receipt.merchant),
            ("receipt.total", receipt.total),
        )
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if not receipt.line_items:
        blanks.append("receipt.line_items")
    blanks += [f"receipt.line_items[{i}].amount" for i, line in enumerate(receipt.line_items) if line.amount is None]
    return blank(*blanks) if blanks else NoFinding()


def receipt_total_matches_charge(ctx: CheckContext) -> Outcome:
    """OSU-GEN-04b: the receipt total equals the charged amount, within total_tolerance.
    Refunds compare by size. A tip on the receipt may explain the difference. A charge higher
    than a receipt with no tip may be a tip written in after printing, so it only needs review."""
    receipt = ctx.receipt
    if receipt.total is None:
        return blank("receipt.total")
    tolerance = _param_decimal(ctx, "total_tolerance")
    charged, total = abs(ctx.txn.amount), abs(receipt.total)
    if abs(charged - total) <= tolerance:
        return NoFinding()
    if receipt.tip is not None and abs(charged - (total + abs(receipt.tip))) <= tolerance:
        return NoFinding()
    evidence = (
        field("transaction.amount", str(ctx.txn.amount)),
        receipt_ref("receipt.total", str(receipt.total), f"Differs by {abs(charged - total)}"),
        policy("params.total_tolerance", str(tolerance)),
    )
    if charged > total and receipt.tip is None:
        return NeedsReview((*evidence, policy(ctx.rule.id, None, "charged more than the receipt: possibly a tip added after printing")))
    if receipt.match_status is MatchStatus.MISMATCH:  # it may be another charge's receipt: never a hard failure
        return NeedsReview((*evidence, policy(ctx.rule.id, None, "the receipt doesn't match this charge")))
    return Finding((*evidence, policy(ctx.rule.id)))


def receipt_belongs_to_charge(ctx: CheckContext) -> Outcome:
    """OSU-GEN-04c: the receipt matched its charge (plan 13's matching: merchant, date, total).
    Matching is approximate, so a mismatch only needs review; too little read to compare can't tell."""
    status = ctx.receipt.match_status
    if status is MatchStatus.MATCHED:
        return NoFinding()
    cited = receipt_ref("receipt.match_status", status.value)
    if status is MatchStatus.UNMATCHED:
        return CannotTell((cited,))
    return NeedsReview((cited, policy(ctx.rule.id, None, "merchant, date, or total is outside the matching tolerance")))


def processing_fee_share(ctx: CheckContext) -> Outcome:
    """OSU-RST-04a: processing or convenience fees are at most max_fee_pct of the subtotal."""
    receipt = ctx.receipt
    hits = matching_lines(receipt, ctx.terms("fee_line_terms"))
    if not hits:
        return NoFinding()
    unpriced = [f"receipt.line_items[{i}].amount" for i, line, _ in hits if line.amount is None]
    if unpriced:
        return blank(*unpriced)
    if receipt.subtotal is None:
        return blank("receipt.subtotal")
    if receipt.subtotal <= 0:
        return CannotTell((receipt_ref("receipt.subtotal", str(receipt.subtotal), "subtotal is not positive"),))
    fees = sum((line.amount for _, line, _ in hits), Decimal(0))
    limit = _param_decimal(ctx, "max_fee_pct")
    if not _over_share(fees, receipt.subtotal, limit):
        return NoFinding()
    return Finding((
        *(line_citation(i, line, term) for i, line, term in hits),
        receipt_ref("receipt.subtotal", str(receipt.subtotal)),
        policy("params.max_fee_pct", str(limit), f"Fees are {_percent(fees, receipt.subtotal)}% of the subtotal"),
    ))


def tip_share(ctx: CheckContext) -> Outcome:
    """OSU-RST-17a: the tip is at most max_tip_pct of the service amount (the subtotal).
    The tip is the receipt's tip field, or else the sum of its tip lines. No tip, nothing to check."""
    receipt = ctx.receipt
    tip_lines = [(i, line) for i, line in enumerate(receipt.line_items) if line.line_type is LineType.TIP]
    if receipt.tip is not None:
        tip, cited = receipt.tip, [receipt_ref("receipt.tip", str(receipt.tip))]
    elif tip_lines:
        unpriced = [f"receipt.line_items[{i}].amount" for i, line in tip_lines if line.amount is None]
        if unpriced:
            return blank(*unpriced)
        tip = sum((line.amount for _, line in tip_lines), Decimal(0))
        cited = [receipt_ref(f"receipt.line_items[{i}]", str(line.amount), "tip line") for i, line in tip_lines]
    else:
        return NoFinding()
    if tip <= 0:
        return NoFinding()
    if receipt.subtotal is None:
        return blank("receipt.subtotal")
    if receipt.subtotal <= 0:
        return CannotTell((receipt_ref("receipt.subtotal", str(receipt.subtotal), "subtotal is not positive"),))
    limit = _param_decimal(ctx, "max_tip_pct")
    if not _over_share(tip, receipt.subtotal, limit):
        return NoFinding()
    return Finding((
        *cited,
        receipt_ref("receipt.subtotal", str(receipt.subtotal)),
        policy("params.max_tip_pct", str(limit), f"Tip is {_percent(tip, receipt.subtotal)}% of the subtotal"),
    ))
