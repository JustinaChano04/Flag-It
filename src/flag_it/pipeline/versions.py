"""The run stamp: what a decision run was made with, beyond the rules file.

`rules_version` hashes only the rules YAML. A run also depends on which inputs the deployment has
(a check needing a missing input is skipped), the checker registry (which checks have code behind
them), and the billing calendar (deadlines). stamp() folds those in so two runs with the same stamp
were made with the same everything.
"""

import hashlib
from collections.abc import Mapping

from flag_it.contracts.rules import RuleSet
from flag_it.decide.checks.base import Checker
from flag_it.decide.checks.calendar import BillingCalendar
from flag_it.decide.checks.deployment import Deployment
from flag_it.decide.checks.registry import CHECKERS, UNSUPPORTED


def stamp(
    rules: RuleSet,
    deployment: Deployment,
    calendar: BillingCalendar,
    checkers: Mapping[str, Checker] = CHECKERS,
    unsupported: Mapping[str, str] = UNSUPPORTED,
) -> str:
    """Pass the checkers and unsupported checks the run actually uses; they default to the real registry."""
    digest = hashlib.sha256()
    for part in (
        rules.rules_version,
        ",".join(sorted(deployment.inputs)),
        ",".join(sorted(checkers)),
        ",".join(sorted(unsupported)),
        calendar.model_dump_json(),
    ):
        digest.update(part.encode())
        digest.update(b"\x00")
    return f"{rules.rules_version}+{digest.hexdigest()[:8]}"
