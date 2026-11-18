"""Which inputs this deployment has. A check that needs any other input is skipped: no flag.

Inputs are listed in inputs.yaml. Adding an input there (when its data is wired in) switches its
checks on, with no change to the rules. See "Inputs gate checks" in policies/README.md.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from flag_it.contracts.rules import Check, Input

DEFAULT_INPUTS_PATH = Path(__file__).with_name("inputs.yaml")
_INPUTS = TypeAdapter(list[Input])


@dataclass(frozen=True)
class Deployment:
    inputs: frozenset[str]

    def __post_init__(self) -> None:
        if "transaction" not in self.inputs:
            raise ValueError("every deployment has the input 'transaction'")

    def missing(self, check: Check) -> list[str]:
        """The inputs this check requires that this deployment doesn't have."""
        return [name for name in check.requires if name not in self.inputs]


def load_deployment(path: Path | None = None) -> Deployment:
    data = yaml.safe_load((path or DEFAULT_INPUTS_PATH).read_text())
    return Deployment(frozenset(_INPUTS.validate_python(data["inputs"])))
