"""Shared checker helpers, and the deployment's input list."""

import pytest
from pydantic import ValidationError

from flag_it.decide.checks.base import CannotTell, Finding, NeedsReview, matching_lines, mentions, unreadable_lines
from flag_it.decide.checks.deployment import Deployment, load_deployment
from tests.decide.checks.helpers import context, line, receipt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("BAR SET-UP FEE", "bar set up"),
        ("2x House Wine", "wine"),
        ("Safety glasses", None),  # "safe" must be a whole word
        ("Winery tour", None),
        (None, None),
    ],
)
def test_terms_match_whole_words_ignoring_case_and_punctuation(text, expected):
    assert mentions(text, ("bar set up", "wine", "safe")) == expected


def test_matching_lines_reports_index_and_term():
    r = receipt(line_items=[line("Burger", "12.00"), line("IPA beer", "7.00")])
    assert [(i, term) for i, _, term in matching_lines(r, ("beer",))] == [(1, "beer")]


def test_an_exception_phrase_cancels_a_match_on_its_line():
    r = receipt(line_items=[line("Root beer float", "4.00"), line("IPA beer", "7.00")])
    assert [i for i, _, _ in matching_lines(r, ("beer",), ("root beer",))] == [1]


def test_lines_without_descriptions_cannot_rule_anything_out():
    assert isinstance(unreadable_lines(receipt(line_items=[line("Burger"), line(None)])), CannotTell)
    assert isinstance(unreadable_lines(receipt()), CannotTell)
    assert unreadable_lines(receipt(line_items=[line("Burger")])) is None


@pytest.mark.parametrize("outcome", [Finding, NeedsReview, CannotTell])
def test_outcomes_other_than_no_finding_need_evidence(outcome):
    with pytest.raises(ValueError):
        outcome(())


def test_terms_must_be_a_list_of_words(rules):
    assert "wine" in context(rules, "OSU-PRH-01b").terms("alcohol_line_terms")
    with pytest.raises(TypeError):
        context(rules, "OSU-RST-04a").terms("max_fee_pct")
    assert context(rules, "OSU-PRH-14a").optional_terms("penalty_line_review_terms") == ("interest", "penalty")
    assert context(rules, "OSU-PRH-19b").optional_terms("postage_line_review_terms") == ()


def test_the_shipped_deployment_has_transactions_and_receipts():
    assert load_deployment().inputs == {"transaction", "receipt"}


def test_a_deployment_without_transactions_or_with_a_bad_input_is_refused(tmp_path):
    with pytest.raises(ValueError):
        Deployment(frozenset({"receipt"}))
    path = tmp_path / "inputs.yaml"
    path.write_text("inputs: [transaction, records]\n")
    with pytest.raises(ValidationError):
        load_deployment(path)


def test_missing_lists_inputs_the_deployment_lacks(rules):
    _, check = rules.check("OSU-TRV-17a")  # requires receipt and table:osu_campus_addresses
    assert load_deployment().missing(check) == ["table:osu_campus_addresses"]
