"""Which checker answers which check, and which checks can't be answered from today's inputs.

CHECKERS maps a check ID to its checker. UNSUPPORTED maps a check ID to the reason it can't be
decided even when its inputs are deployed: the receipt extraction doesn't hold the fact it needs.
Those checks report not_evaluated with the reason. tests/decide/checks/test_registry.py keeps
both lists complete for the deployed inputs.
"""

from collections.abc import Mapping
from types import MappingProxyType

from flag_it.decide.checks import amounts, lines
from flag_it.decide.checks.base import Checker

CHECKERS: Mapping[str, Checker] = MappingProxyType({
    "OSU-LIM-01a": amounts.single_transaction_limit,
    "OSU-GEN-04a": amounts.itemized_receipt,
    "OSU-GEN-04b": amounts.receipt_total_matches_charge,
    "OSU-GEN-04c": amounts.receipt_belongs_to_charge,
    "OSU-RST-04a": amounts.processing_fee_share,
    "OSU-RST-17a": amounts.tip_share,
    "OSU-PRH-01b": lines.no_alcohol_lines,
    "OSU-PRH-12b": lines.insurance_is_physical_damage_only,
    "OSU-PRH-14a": lines.no_penalty_lines,
    "OSU-PRH-19b": lines.no_postage_lines,
    "OSU-PRH-22a": lines.no_trade_in_lines,
    "OSU-TRV-04a": lines.premium_fare_lines,
    "OSU-TRV-08a": lines.no_personal_folio_lines,
    "OSU-TRV-09a": lines.registration_and_lodging_together,
    "OSU-TRV-17b": lines.no_ticket_lines,
})

_NO_LOCATION = "the receipt extraction has no merchant or rental location"
_NO_TERM = "the receipt extraction has no service term or period"
_NO_PREPAYMENT = "the receipt extraction doesn't say whether it was prepaid"

UNSUPPORTED: Mapping[str, str] = MappingProxyType({
    "OSU-SPL-01a": "needs the cardholder's other charges; window checks wait for a history reader",
    "OSU-PRH-03a": "the receipt extraction has no subject or provider country",
    "OSU-PRH-04a": "the receipt extraction has no receipt or ship date for the goods",
    "OSU-PRH-06a": "the receipt extraction has no delivery or service date",
    "OSU-PRH-15b": _NO_TERM,
    "OSU-PRH-16a": _NO_TERM,
    "OSU-PRH-17a": _NO_LOCATION,
    "OSU-RST-16a": _NO_TERM,
    "OSU-TRV-05a": "the receipt extraction has no check-in date or cancellation policy",
    "OSU-TRV-07a": _NO_LOCATION,
    "OSU-TRV-12a": _NO_PREPAYMENT,
    "OSU-TRV-13a": _NO_LOCATION,
    "OSU-TRV-13b": _NO_PREPAYMENT,
})
