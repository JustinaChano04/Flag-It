import pytest

from flag_it.contracts.rules import RuleSet, load_rules


@pytest.fixture(scope="module")
def rules() -> RuleSet:
    return load_rules()
