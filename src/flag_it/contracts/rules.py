"""Models and loader for the rules YAML. The field meanings are in the YAML's header comment."""

import hashlib
import os
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import Field, model_validator

from flag_it.contracts.common import CheckId, InputModel, NonEmptyStr, RuleId, check_belongs_to_rule
from flag_it.contracts.enums import CheckMethod, Severity

_REPO_RULES_PATH = Path(__file__).resolve().parents[3] / "policies" / "osu" / "osu_rules.yaml"


def default_rules_path() -> Path:
    """FLAG_IT_RULES_PATH if set (containers and installed copies), else the repo's file."""
    return Path(os.environ.get("FLAG_IT_RULES_PATH", _REPO_RULES_PATH))


DEFAULT_RULES_PATH = default_rules_path()

ParamValue = int | float | str | bool | list[int | float | str]
Input = Annotated[str, Field(pattern=r"^(transaction|receipt|table:[a-z0-9_]+|records:[a-z0-9_]+)$")]


class UnknownParamError(KeyError):
    """A check asked for a param its rule does not define."""


class Policy(InputModel):
    name: NonEmptyStr
    version: NonEmptyStr
    source_file: NonEmptyStr
    scope: NonEmptyStr


class SourceRef(InputModel):
    section: NonEmptyStr
    page: int | str


class When(InputModel):
    check: CheckId | None = None
    any_of: list[CheckId] | None = None
    result: bool | Literal["pass", "fail", "violation", "allowed", "unclear"]

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.check is None) == (self.any_of is None):
            raise ValueError("when needs exactly one of check or any_of")
        return self

    def referenced(self) -> list[str]:
        return [self.check] if self.check else list(self.any_of or [])


class Timing(InputModel):
    due: Literal["purchase+24h", "cycle_end", "cycle_signoff"]


class Screen(InputModel):
    match: NonEmptyStr
    promote_with: str | None = None


class DecisionCriteria(InputModel):
    violation: str | None = None
    allowed: str | None = None
    unclear: str | None = None
    flag: str | None = None


class Check(InputModel):
    id: CheckId
    ask: NonEmptyStr
    pattern: Literal[
        "threshold", "list_membership", "line_item", "document_presence",
        "aggregation", "cross_reference", "purpose",
    ]
    method: CheckMethod
    requires: Annotated[list[Input], Field(min_length=1)]
    uses: list[Input] = []
    scope: Literal[
        "transaction", "card", "cardholder_window", "department_window", "billing_cycle", "trip",
    ]
    role: Literal["gate"] | None = None
    when: When | None = None
    timing: Timing | None = None
    screen: Screen | None = None
    decision: DecisionCriteria | None = None

    @model_validator(mode="after")
    def _llm_shape(self) -> Self:
        is_llm = self.method is CheckMethod.LLM
        if is_llm and (self.pattern != "purpose" or self.decision is None):
            raise ValueError(f"{self.id}: llm checks need pattern purpose and decision criteria")
        if not is_llm and (self.decision is not None or self.screen is not None):
            raise ValueError(f"{self.id}: only llm checks have decision or screen")
        return self


class Rule(InputModel):
    id: RuleId
    title: NonEmptyStr
    topic: Literal["limits", "vendor", "process", "items", "travel"]
    text: NonEmptyStr
    source: SourceRef
    severity: Severity
    applies_to: Annotated[list[NonEmptyStr], Field(min_length=1)]
    params: dict[str, ParamValue] = {}
    hints: str | None = None
    notes: str | None = None
    status: Literal["active", "retired"] = "active"
    checks: Annotated[list[Check], Field(min_length=1)]

    @model_validator(mode="after")
    def _checks_extend_rule_id(self) -> Self:
        for check in self.checks:
            if not check_belongs_to_rule(self.id, check.id):
                raise ValueError(f"check {check.id} does not belong to rule {self.id}")
        return self

    def param(self, name: str) -> ParamValue:
        try:
            return self.params[name]
        except KeyError:
            raise UnknownParamError(f"rule {self.id} has no param {name!r}") from None


class RuleSet(InputModel):
    policy: Policy
    categories: dict[str, NonEmptyStr]
    referenced_documents_not_ingested: list[str] = []
    rules: list[Rule]
    rules_version: NonEmptyStr  # added by load_rules, not written in the YAML

    @model_validator(mode="after")
    def _cross_references(self) -> Self:
        rule_ids = [r.id for r in self.rules]
        check_ids = [c.id for r in self.rules for c in r.checks]
        for ids, kind in ((rule_ids, "rule"), (check_ids, "check")):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            if dupes:
                raise ValueError(f"duplicate {kind} ids: {dupes}")
        known = set(check_ids)
        for rule in self.rules:
            unknown = set(rule.applies_to) - set(self.categories) - {"all"}
            if unknown:
                raise ValueError(f"rule {rule.id} applies_to unknown categories: {sorted(unknown)}")
            for check in rule.checks:
                missing = [ref for ref in (check.when.referenced() if check.when else []) if ref not in known]
                if missing:
                    raise ValueError(f"check {check.id} 'when' references unknown checks: {missing}")
        return self

    def has_category(self, category: str) -> bool:
        return category in self.categories

    def rule(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(rule_id)

    def check(self, check_id: str) -> tuple[Rule, Check]:
        for rule in self.rules:
            for check in rule.checks:
                if check.id == check_id:
                    return rule, check
        raise KeyError(check_id)

    def checks_for(self, category: str, method: CheckMethod) -> list[tuple[Rule, Check]]:
        """Active checks of one method that apply to a category, in file order."""
        return [
            (rule, check)
            for rule in self.rules
            if rule.status == "active" and ("all" in rule.applies_to or category in rule.applies_to)
            for check in rule.checks
            if check.method is method
        ]


class _RulesFile(InputModel):
    """Shape check of the whole file before rules_version is computed from it."""

    policy: Policy
    categories: dict[str, NonEmptyStr]
    referenced_documents_not_ingested: list[str] = []
    rules: list[Rule]


def load_rules(path: Path | None = None) -> RuleSet:
    path = path or default_rules_path()
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    # Validate first, so an empty or malformed file is a ValidationError, not a KeyError.
    parsed = _RulesFile.model_validate(data if isinstance(data, dict) else {"_": data})
    version = f"{parsed.policy.version}+{hashlib.sha256(raw).hexdigest()[:12]}"
    return RuleSet.model_validate({**data, "rules_version": version})
