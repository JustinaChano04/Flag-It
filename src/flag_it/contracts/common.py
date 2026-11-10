"""Base models, shared field types, and the contract version."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# Bump on any change to a model's fields. See "Versioning" in docs/contracts.md.
CONTRACT_VERSION = "1.0.0"


class ContractModel(BaseModel):
    """Common root. Use InputModel or RecordModel, never this directly."""

    model_config = ConfigDict(frozen=True, protected_namespaces=())


class InputModel(ContractModel):
    """Data from outside the system (API requests, the agent's output, the rules YAML).
    Unknown fields are errors, so typos fail loudly."""

    model_config = ConfigDict(extra="forbid")


class RecordModel(ContractModel):
    """Data the system saves, queues, or returns. Unknown fields are ignored, so a reader
    on an older minor version can still read a record with a new optional field."""

    model_config = ConfigDict(extra="ignore")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("money must not be a float; pass a string or Decimal")
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(max_digits=12, decimal_places=2, allow_inf_nan=False),
]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
NonEmptyStr = Annotated[str, Field(min_length=1)]
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
RuleId = Annotated[str, Field(pattern=r"^[A-Z0-9]+(?:-[A-Z0-9]+)+$")]
CheckId = Annotated[str, Field(pattern=r"^[A-Z0-9]+(?:-[A-Z0-9]+)+[a-z]+$")]
JsonScalar = str | int | float | bool | None
# Why a run went to a person. See "Decision run" in docs/contracts.md.
EscalationReason = Annotated[
    str,
    Field(
        pattern=(
            r"^((unsure|low_confidence):[A-Z0-9]+(-[A-Z0-9]+)+[a-z]+"
            r"|citation_unresolved|invalid_output|agent_failed|review_conflict)$"
        )
    ),
]


def check_belongs_to_rule(rule_id: str, check_id: str) -> bool:
    """True when check_id is rule_id plus lowercase letters, e.g. OSU-LIM-01 and OSU-LIM-01a."""
    suffix = check_id.removeprefix(rule_id)
    return suffix != check_id and suffix.isalpha() and suffix.islower()


class IncompatibleContractVersion(ValueError):
    """Raised when data was written under a different major contract version."""


def major(version: str) -> int:
    return int(version.split(".")[0])


def ensure_compatible(version: str) -> None:
    try:
        theirs = major(version)
    except ValueError as err:
        raise IncompatibleContractVersion(f"not a contract version: {version!r}") from err
    if theirs != major(CONTRACT_VERSION):
        raise IncompatibleContractVersion(
            f"data has contract version {version}, this code reads {CONTRACT_VERSION}"
        )


def require_version(data: Mapping[str, Any]) -> None:
    """For saved JSON read back later: the stamp must be present and the major version must match."""
    if "contract_version" not in data:
        raise IncompatibleContractVersion("saved data has no contract_version")
    ensure_compatible(str(data["contract_version"]))
