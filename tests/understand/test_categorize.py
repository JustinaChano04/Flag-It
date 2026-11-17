"""The lookup categorizer: MCC description -> category ID from the rules YAML, with a confidence."""

import re

import pytest

from flag_it.contracts.enums import CategoryMethod
from flag_it.contracts.examples import TXN_ID, normalized
from flag_it.contracts.rules import load_rules
from flag_it.understand.categorize import FALLBACK_CATEGORY, categorize, load_lookup, mcc_key


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture(scope="module")
def lookup(rules):
    return load_lookup(rules)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("EATING PLACES, RESTAURANTS", "EATING PLACES RESTAURANTS"),
        ("EATING PLACES  RESTAURANTS", "EATING PLACES RESTAURANTS"),  # as the export writes it
        ("  grocery stores  supermarkets ", "GROCERY STORES SUPERMARKETS"),
        ("AT&T WIRELESS", "AT&T WIRELESS"),
    ],
)
def test_keys_ignore_case_spacing_and_punctuation(text, expected):
    assert mcc_key(text) == expected


def test_the_packaged_lookup_loads_and_every_category_is_in_the_rules(rules, lookup):
    assert re.fullmatch(r"lookup-[0-9a-f]{12}", lookup.version)
    assert len(lookup.entries) > 300
    assert all(rules.has_category(category) for category, _ in lookup.entries.values())


def test_a_known_mcc_gets_its_category(lookup):
    result = categorize(normalized(mcc_description="EATING PLACES, RESTAURANTS"), lookup)
    assert (result.txn_id, result.category, result.method) == (TXN_ID, "meals_refreshments", CategoryMethod.LOOKUP)
    assert result.model_version == lookup.version
    assert 0 < result.confidence < 1


def test_an_airline_mcc_is_high_confidence(lookup):
    result = categorize(normalized(mcc_description="AMERICAN AIRLINES"), lookup)
    assert (result.category, result.confidence) == ("airfare_baggage", 0.9)


def test_an_unknown_mcc_is_other_unclear_with_no_confidence_and_logged(lookup, caplog):
    result = categorize(normalized(mcc_description="SOMETHING NEW"), lookup)
    assert (result.category, result.confidence) == (FALLBACK_CATEGORY, 0.0)
    assert "'SOMETHING NEW' is not in lookup" in caplog.text


def test_the_version_changes_when_the_file_changes(rules, tmp_path):
    path = tmp_path / "lookup.csv"
    path.write_text("MCC_DESCRIPTION,category,confidence\nAMERICAN AIRLINES,Airfare & baggage,high\n")
    first = load_lookup(rules, path)
    path.write_text("MCC_DESCRIPTION,category,confidence\nAMERICAN AIRLINES,Airfare & baggage,medium\n")
    assert load_lookup(rules, path).version != first.version


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("AMERICAN AIRLINES,Spaceflight,high", "not a category in the rules"),
        ("AMERICAN AIRLINES,Airfare & baggage,certain", "unknown confidence"),
    ],
)
def test_a_bad_lookup_row_is_refused(rules, tmp_path, row, message):
    path = tmp_path / "lookup.csv"
    path.write_text(f"MCC_DESCRIPTION,category,confidence\n{row}\n")
    with pytest.raises(ValueError, match=message):
        load_lookup(rules, path)


def test_two_rows_for_one_key_must_agree(rules, tmp_path):
    path = tmp_path / "lookup.csv"
    path.write_text(
        "MCC_DESCRIPTION,category,confidence\n"
        "EATING PLACES  RESTAURANTS,Meals & refreshments,medium\n"
        '"EATING PLACES, RESTAURANTS",Lodging,high\n'
    )
    with pytest.raises(ValueError, match="two rows"):
        load_lookup(rules, path)
