"""Which checker answers which check, and which checks can't be answered from today's inputs.

CHECKERS maps a check ID to its checker. UNSUPPORTED maps a check ID to the reason it can't be
decided even when its inputs are deployed: the receipt extraction doesn't hold the fact it needs.
Those checks report not_evaluated with the reason. tests/decide/checks/test_registry.py keeps
both lists complete for the deployed inputs.
"""

from collections.abc import Mapping
from types import MappingProxyType

from flag_it.decide.checks.base import Checker

CHECKERS: Mapping[str, Checker] = MappingProxyType({})

UNSUPPORTED: Mapping[str, str] = MappingProxyType({})
