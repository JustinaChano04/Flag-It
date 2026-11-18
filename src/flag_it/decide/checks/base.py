"""What a rule checker receives and returns, and helpers the checkers share.

A checker answers one check's question about one combined expense. It returns:
- Finding: certain evidence of what the check's `ask` rules out (for a gate: what it looks for);
- NeedsReview: evidence that suggests it but isn't certain, such as an ambiguous word;
- NoFinding: nothing found;
- CannotTell: the inputs exist but don't settle it, usually because the reader left a field blank.

Only certain evidence fails a check: code checks score 1.0. A blank field never fails one (the
reader may have missed it), and an ambiguous word sends the run to be looked at instead.
The engine (engine.py) turns results into flags.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from flag_it.contracts.decide import Citation
from flag_it.contracts.enums import EvidenceKind
from flag_it.contracts.rules import Check, Rule
from flag_it.contracts.snapshot import CombinedExpense
from flag_it.contracts.transactions import NormalizedTransaction
from flag_it.contracts.understand import ReceiptExtraction, ReceiptLineItem


@dataclass(frozen=True)
class Finding:
    evidence: tuple[Citation, ...]

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("a finding needs at least one citation")


@dataclass(frozen=True)
class NeedsReview:
    evidence: tuple[Citation, ...]

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("needs-review needs at least one citation")


@dataclass(frozen=True)
class NoFinding:
    pass


@dataclass(frozen=True)
class CannotTell:
    evidence: tuple[Citation, ...]

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("cannot-tell needs at least one citation saying why")


Outcome = Finding | NeedsReview | NoFinding | CannotTell


@dataclass(frozen=True)
class CheckContext:
    expense: CombinedExpense
    rule: Rule
    check: Check

    @property
    def txn(self) -> NormalizedTransaction:
        return self.expense.transaction

    @property
    def receipt(self) -> ReceiptExtraction:
        """The engine only calls a checker that requires a receipt when there is one."""
        if self.expense.receipt is None:
            raise LookupError(f"{self.check.id} needs a receipt and the expense has none")
        return self.expense.receipt

    def terms(self, name: str) -> tuple[str, ...]:
        """A word-list param of the rule, such as alcohol_line_terms."""
        value = self.rule.param(name)
        if not isinstance(value, list) or not all(isinstance(term, str) for term in value):
            raise TypeError(f"param {name!r} of rule {self.rule.id} must be a list of words")
        return tuple(value)

    def optional_terms(self, name: str) -> tuple[str, ...]:
        """Like terms(), but an absent param is an empty list (review and exception words are optional)."""
        return self.terms(name) if name in self.rule.params else ()


Checker = Callable[[CheckContext], Outcome]


def field(ref: str, value=None, note: str | None = None) -> Citation:
    return Citation(kind=EvidenceKind.FIELD, ref=ref, value=value, note=note)


def receipt_ref(ref: str, value=None, note: str | None = None) -> Citation:
    return Citation(kind=EvidenceKind.RECEIPT, ref=ref, value=value, note=note)


def policy(ref: str, value=None, note: str | None = None) -> Citation:
    return Citation(kind=EvidenceKind.POLICY, ref=ref, value=value, note=note)


def blank(*refs: str) -> CannotTell:
    """The reader left these receipt fields blank, so the check can't tell."""
    return CannotTell(tuple(receipt_ref(ref, None, "blank: the reader could not read it") for ref in refs))


def _words(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split()) + " "


def mentions(text: str | None, terms: tuple[str, ...]) -> str | None:
    """The first term that appears in text as whole words, ignoring case and punctuation, or None.
    "Bar set-up" matches the term "bar set up"; "safety" does not match "safe"."""
    if not text:
        return None
    haystack = _words(text)
    for term in terms:
        if _words(term) in haystack:
            return term
    return None


def matching_lines(
    receipt: ReceiptExtraction, terms: tuple[str, ...], except_terms: tuple[str, ...] = ()
) -> list[tuple[int, ReceiptLineItem, str]]:
    """(index, line, matched term) for every line whose description mentions a term, skipping lines
    that mention an exception ("special interest" cancels "interest")."""
    hits = []
    for index, line in enumerate(receipt.line_items):
        term = mentions(line.description, terms)
        if term is not None and mentions(line.description, except_terms) is None:
            hits.append((index, line, term))
    return hits


def line_citation(index: int, line: ReceiptLineItem, term: str) -> Citation:
    return receipt_ref(f"receipt.line_items[{index}]", line.description, f"mentions {term!r}")


def unreadable_lines(receipt: ReceiptExtraction) -> CannotTell | None:
    """CannotTell when the lines can't rule anything out: there are none, or one has no description."""
    if not receipt.line_items:
        return CannotTell((receipt_ref("receipt.line_items", None, "no line items were read"),))
    blanks = [i for i, line in enumerate(receipt.line_items) if not (line.description or "").strip()]
    if blanks:
        return blank(*(f"receipt.line_items[{i}].description" for i in blanks))
    return None
