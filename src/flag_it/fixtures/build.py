"""Build the shared fixtures in fixtures/ from the contract models and the rules YAML.

    python -m flag_it.fixtures.build           # rewrite fixtures/*.json and fixtures/catalog.md
    python -m flag_it.fixtures.build --check   # exit 1 if the committed files differ from a fresh build

Nothing in fixtures/ is edited by hand. IDs are uuid5 of the fixture name, times are fixed, and
amounts at a limit come from the rule's params. Rebuild after any change to the contracts or the
rules YAML. What each fixture covers: fixtures/catalog.md.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from flag_it.contracts.decide import AgentOutput, DecisionRun, Flag, ScreenerResult
from flag_it.contracts.enums import AgentResult
from flag_it.contracts.jobs import InvestigateJob, ReadReceiptJob
from flag_it.contracts.review import ReviewOutcome
from flag_it.contracts.rules import RuleSet, load_rules
from flag_it.contracts.snapshot import CombinedExpense, CombinedExpenseSnapshot
from flag_it.contracts.transactions import NormalizedTransaction, RawTransaction
from flag_it.contracts.understand import AnomalyResult, CategoryResult, ReceiptExtraction
from flag_it.db.rows import ReceiptFile
from flag_it.fixtures import fixtures_dir

NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/JustinaChano04/Flag-It/fixtures")

DECIDED_AT = datetime(2025, 3, 3, 15, 0, tzinfo=timezone.utc)  # initial runs
LATE_AT = datetime(2025, 3, 6, 15, 0, tzinfo=timezone.utc)  # the late folio's rerun
SIGNOFF = datetime(2025, 4, 10, 23, 59, tzinfo=timezone.utc)  # billing-cycle sign-off: due_at of pending checks
DEADLINE_AT = datetime(2025, 4, 11, 6, 0, tzinfo=timezone.utc)  # the deadline job's rerun

READER = "qwen3-vl:8b-q4_K_M"
CATEGORIZER = "lookup-2025-10"
ANOMALY_MODEL = "robust-z-1"
FIXTURE_RULES_VERSION = "fixtures-1"  # fixed on purpose: see "Global constraints"


def fid(kind: str, name: str) -> UUID:
    """A stable ID for one fixture record, so a rebuild never changes it."""
    return uuid5(NAMESPACE, f"{kind}:{name}")


@dataclass(frozen=True)
class TxnSpec:
    category: str  # a category ID from the rules YAML
    mcc_description: str  # an MCC label from data_exploration/mcc_to_category.csv
    merchant: str  # merchant text as the card processor sent it
    merchant_norm: str
    amount: str
    note: str  # what the fixture is for; goes into catalog.md
    last_name: str = "RIVERA"
    first_initial: str = "M"
    transaction_date: date = date(2025, 2, 27)
    mcc_code: str | None = None
    business_purpose: str | None = None


# Merchants are made up. MCC labels are real labels from the public export.
CATEGORY_TXNS: dict[str, TxnSpec] = {
    "cat_airfare_baggage": TxnSpec(
        "airfare_baggage", "AIRLINES  AIR CARRIERS", "PRAIRIE AIR 0012345678901", "PRAIRIE AIR", "386.20",
        "Airfare."),
    "cat_lodging": TxnSpec(
        "lodging", "LODGING  HOTELS  MOTELS  RESORTS", "CIMARRON INN STILLWATER", "CIMARRON INN STILLWATER",
        "289.00", "One hotel night."),
    "cat_ground_transportation": TxnSpec(
        "ground_transportation", "TAXICABS/LIMOUSINES", "REDDIRT CAB CO", "REDDIRT CAB CO", "38.50", "Cab ride."),
    "cat_parking_tolls": TxnSpec(
        "parking_tolls", "TOLLS  ROAD AND BRIDGE FEES", "TURNPIKE TOLL 0447", "TURNPIKE TOLL", "6.75",
        "Turnpike toll."),
    "cat_meals_refreshments": TxnSpec(
        "meals_refreshments", "EATING PLACES  RESTAURANTS", "SQ *CAMPUS CORNER CAFE", "CAMPUS CORNER CAFE",
        "84.60", "Restaurant meal."),
    "cat_instructional_research_food": TxnSpec(
        "instructional_research_food", "GROCERY STORES  SUPERMARKETS", "PRAIRIE FRESH MARKET #112",
        "PRAIRIE FRESH MARKET", "64.18", "Groceries for a research study."),
    "cat_office_general_supplies": TxnSpec(
        "office_general_supplies", "BOOK STORES", "CHISHOLM BOOKS", "CHISHOLM BOOKS", "47.25", "Books."),
    "cat_lab_research_medical_supplies": TxnSpec(
        "lab_research_medical_supplies", "LAB/MEDICAL/DENTAL/OPHTHALMIC HOSPITAL E", "REDBUD SCIENTIFIC",
        "REDBUD SCIENTIFIC", "612.40", "Lab supplies."),
    "cat_equipment_tools": TxnSpec(
        "equipment_tools", "HOME SUPPLY WAREHOUSE STORES", "SOONER HOME SUPPLY #0417", "SOONER HOME SUPPLY",
        "143.88", "Hardware."),
    "cat_clothing_ppe": TxnSpec(
        "clothing_ppe", "MEN S WOMENS AND CHILDREN S UNIFORMS AND", "OKIE WORKWEAR", "OKIE WORKWEAR", "96.00",
        "Work uniforms."),
    "cat_software_subscriptions": TxnSpec(
        "software_subscriptions", "COMPUTER SOFTWARE STORES", "DATAPLAINS SOFTWARE", "DATAPLAINS SOFTWARE",
        "249.00", "Software license."),
    "cat_registrations_memberships": TxnSpec(
        "registrations_memberships", "MEMBERSHIP ORGANIZATIONS NOT ELSEWHERE C", "SOUTHWEST SOCIETY OF ENGINEERS",
        "SOUTHWEST SOCIETY OF ENGINEERS", "175.00", "Society membership."),
    "cat_services_shipping_fees": TxnSpec(
        "services_shipping_fees", "BUSINESS SERVICES NOT ELSEWHERE CLASSIFI", "PRAIRIE PRINT AND SHIP",
        "PRAIRIE PRINT AND SHIP", "58.30", "Printing service."),
    "cat_utilities_facilities": TxnSpec(
        "utilities_facilities", "UTILITIES-ELEC/GAS/HEAT OIL/SANITARY/WTR", "CITY OF STILLWATER UTIL",
        "CITY OF STILLWATER UTIL", "212.67", "Utility bill."),
    "cat_restricted_items": TxnSpec(
        "restricted_items", "MISCELLANEOUS SPECIALTY RETAIL", "PRAIRIE TROPHY AND AWARDS",
        "PRAIRIE TROPHY AND AWARDS", "250.00", "Service award plaques for staff."),
    "cat_other_unclear": TxnSpec(
        "other_unclear", "ARTIST SUPPLY STORES  CRAFT SHOPS", "PRAIRIE CRAFTS", "PRAIRIE CRAFTS", "33.10",
        "Craft supplies. The categorizer is unsure."),
}

# Transactions decided more than once. Their snapshots are named <txn>_1, <txn>_2.
CHAIN_TXNS = frozenset({"lodging_stay", "missing_document"})


def transactions(rules: RuleSet) -> dict[str, TxnSpec]:
    """Every fixture transaction: one per spend category, plus variants at the edges."""
    limit = Decimal(str(rules.rule("OSU-LIM-01").param("max_single_transaction"))).quantize(Decimal("0.01"))
    equipment = CATEGORY_TXNS["cat_equipment_tools"]
    office = CATEGORY_TXNS["cat_office_general_supplies"]
    lodging = CATEGORY_TXNS["cat_lodging"]
    return {
        **CATEGORY_TXNS,
        "over_single_limit": replace(
            equipment, amount=str(limit + Decimal("0.01")), note="One cent over OSU-LIM-01 max_single_transaction."),
        "at_single_limit": replace(
            equipment, amount=str(limit), note="Exactly OSU-LIM-01 max_single_transaction, which passes."),
        "refund": replace(office, amount="-47.25", note="A refund: negative amount."),
        "with_purpose": replace(
            CATEGORY_TXNS["cat_meals_refreshments"], mcc_code="5812",
            business_purpose="Lunch for a visiting seminar speaker",
            note="Richer feed: has mcc_code and business_purpose."),
        "new_cardholder": replace(
            office, last_name="NGUYEN", first_initial="T", note="Too little history for an anomaly score."),
        "unusual_amount": replace(
            CATEGORY_TXNS["cat_lab_research_medical_supplies"], amount="4820.00", note="High anomaly score."),
        "receipt_matched": replace(lodging, amount="129.00", note="Receipt read and matched. No tax lines."),
        "receipt_mismatch": replace(office, amount="86.40", note="Receipt total differs from the charge."),
        "receipt_unreadable": replace(office, amount="19.99", note="Receipt could not be read: every field empty."),
        "lodging_stay": replace(
            lodging, amount="319.06", note="Decided without a receipt. The folio arrives later, with a tax line."),
        "missing_document": replace(office, amount="122.50", note="No itemized receipt by cycle sign-off."),
    }


def _dd_mon_yy(day: date) -> str:
    return day.strftime("%d-%b-%y").upper()


def raw_transaction(name: str, spec: TxnSpec) -> RawTransaction:
    """The row as the intake API would store it: every field text."""
    return RawTransaction(
        raw_id=fid("raw", name),
        source="fixtures",
        external_id=name,
        calendar_year=str(spec.transaction_date.year),
        calendar_month=str(spec.transaction_date.month),
        agencynbr="01000",
        agencyname="OKLAHOMA STATE UNIVERSITY",
        last_name=spec.last_name,
        first_initial=spec.first_initial,
        amount=spec.amount,
        merchant_name=spec.merchant,
        transaction_date=_dd_mon_yy(spec.transaction_date),
        post_date=_dd_mon_yy(spec.transaction_date + timedelta(days=1)),
        mcc_description=spec.mcc_description,
        mcc_code=spec.mcc_code,
        business_purpose=spec.business_purpose,
    )


def normalized_transaction(name: str, spec: TxnSpec) -> NormalizedTransaction:
    return NormalizedTransaction(
        txn_id=fid("txn", name),
        raw_id=fid("raw", name),
        agency_id="01000",
        cardholder_id=f"01000|{spec.last_name}|{spec.first_initial}",
        merchant_norm=spec.merchant_norm,
        mcc_description=spec.mcc_description,
        mcc_code=spec.mcc_code,
        amount=spec.amount,
        transaction_date=spec.transaction_date,
        post_date=spec.transaction_date + timedelta(days=1),
        business_purpose=spec.business_purpose,
        normalizer_version="1",
    )


def category_result(name: str, spec: TxnSpec) -> CategoryResult:
    unsure = spec.category == "other_unclear"
    return CategoryResult(
        txn_id=fid("txn", name),
        model_version="lgbm-cat-1" if unsure else CATEGORIZER,
        category=spec.category,
        confidence=0.35 if unsure else 0.9,
        method="model" if unsure else "lookup",
    )


ANOMALY_OVERRIDES: dict[str, dict] = {
    "new_cardholder": {"status": "insufficient_history", "score": None, "history_length": 2},
    "unusual_amount": {"score": 7.4},
}


def anomaly_result(name: str, spec: TxnSpec) -> AnomalyResult:
    data = {
        "txn_id": fid("txn", name),
        "model_version": ANOMALY_MODEL,
        "status": "scored",
        "score": 0.8,
        "history_length": 24,
        "as_of": datetime.combine(spec.transaction_date, time(0), tzinfo=timezone.utc),
    }
    return AnomalyResult(**(data | ANOMALY_OVERRIDES.get(name, {})))


RECEIPT_TXN = {
    "receipt_matched": "receipt_matched",
    "receipt_mismatch": "receipt_mismatch",
    "receipt_unreadable": "receipt_unreadable",
    "lodging_stay_folio": "lodging_stay",
}


def receipts() -> dict[str, ReceiptExtraction]:
    """Receipt extractions by name. Each was uploaded against the transaction in RECEIPT_TXN."""

    def receipt(name: str, **fields) -> ReceiptExtraction:
        return ReceiptExtraction(
            receipt_id=fid("receipt", name), txn_id=fid("txn", RECEIPT_TXN[name]), reader_model=READER, **fields
        )

    room = {"description": "Room, 1 night", "quantity": "1", "line_type": "room"}
    return {
        "receipt_matched": receipt(
            "receipt_matched", match_status="matched", merchant="Cimarron Inn", receipt_date=date(2025, 2, 27),
            subtotal="129.00", total="129.00",
            line_items=[room | {"unit_price": "129.00", "amount": "129.00"}],
        ),
        "receipt_mismatch": receipt(
            "receipt_mismatch", match_status="mismatch", merchant="Chisholm Books", receipt_date=date(2025, 2, 27),
            subtotal="68.40", total="68.40",
            line_items=[{"description": "Field guide", "quantity": "2", "unit_price": "34.20", "amount": "68.40"}],
        ),
        "receipt_unreadable": receipt("receipt_unreadable", match_status="unmatched"),
        "lodging_stay_folio": receipt(
            "lodging_stay_folio", match_status="matched", merchant="Cimarron Inn", receipt_date=date(2025, 2, 28),
            subtotal="289.00", tax="30.06", total="319.06",
            line_items=[
                room | {"unit_price": "289.00", "amount": "289.00"},
                {"description": "State and city lodging tax", "quantity": "1", "amount": "30.06", "line_type": "tax"},
            ],
        ),
    }


def receipt_file(name: str, receipt: ReceiptExtraction) -> ReceiptFile:
    """The uploaded-file row. The storage key points at nothing: fixtures have no images."""
    uploaded = LATE_AT if name == "lodging_stay_folio" else DECIDED_AT
    return ReceiptFile(
        receipt_id=receipt.receipt_id,
        txn_id=receipt.txn_id,
        storage_key=f"fixtures/{name}.pdf",
        content_type="application/pdf",
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        size_bytes=2048,
        uploaded_at=uploaded - timedelta(hours=1),
    )


@dataclass(frozen=True)
class SnapshotSpec:
    txn: str
    receipt: str | None
    taken_at: datetime
    note: str | None = None  # for catalog.md; the transaction's note is used when empty


CHAIN_SNAPSHOTS = {
    "lodging_stay_1": SnapshotSpec("lodging_stay", None, DECIDED_AT, "Lodging, before the folio arrives."),
    "lodging_stay_2": SnapshotSpec(
        "lodging_stay", "lodging_stay_folio", LATE_AT, "Same stay with the folio, which has a lodging tax line."),
    "missing_document_1": SnapshotSpec("missing_document", None, DECIDED_AT, "Before cycle sign-off."),
    "missing_document_2": SnapshotSpec("missing_document", None, DEADLINE_AT, "After sign-off, still no receipt."),
}


def snapshot_specs(rules: RuleSet) -> dict[str, SnapshotSpec]:
    """One snapshot per transaction, named after it, except the chains, which get one per run."""
    found = receipts()
    single = {
        name: SnapshotSpec(name, name if name in found else None, DECIDED_AT)
        for name in transactions(rules)
        if name not in CHAIN_TXNS
    }
    return single | CHAIN_SNAPSHOTS


def snapshots(rules: RuleSet) -> dict[str, CombinedExpenseSnapshot]:
    txns, found = transactions(rules), receipts()
    result = {}
    for name, spec in snapshot_specs(rules).items():
        txn = txns[spec.txn]
        payload = CombinedExpense(
            transaction=normalized_transaction(spec.txn, txn),
            receipt=found[spec.receipt] if spec.receipt else None,
            category=category_result(spec.txn, txn),
            anomaly=anomaly_result(spec.txn, txn),
        )
        result[name] = CombinedExpenseSnapshot.build(payload, snapshot_id=fid("snapshot", name), created_at=spec.taken_at)
    return result


STAND_IN = ScreenerResult(probability=1.0, threshold=0.5, model_version="stand-in-1")
TRAINED = ScreenerResult(probability=0.04, threshold=0.2, model_version="screener-lgbm-1")

# The llm checks every fixture investigation sends. Both apply to every category.
AGENT_CHECKS = ("OSU-GEN-06a", "OSU-PRH-09a")


def decision_runs(rules: RuleSet, snaps: dict[str, CombinedExpenseSnapshot]) -> dict[str, DecisionRun]:
    def run(name: str, snapshot: str, *, created_at=DECIDED_AT, trigger="initial", replaces=None, **fields):
        snap = snaps[snapshot]
        return DecisionRun(
            decision_id=fid("decision", name),
            txn_id=snap.txn_id,
            snapshot_id=snap.snapshot_id,
            trigger=trigger,
            replaces_decision_id=fid("decision", replaces) if replaces else None,
            rules_version=FIXTURE_RULES_VERSION,
            created_at=created_at,
            **fields,
        )

    agent = {"decided_by": "agent", "screener": STAND_IN}
    guardrails = {"route": "human_review", "decided_by": "guardrails", "screener": STAND_IN}
    return {
        "flag_over_limit": run("flag_over_limit", "over_single_limit", route="flag", decided_by="rules"),
        "auto_approved": run(
            "auto_approved", "cat_office_general_supplies", route="auto_approve", decided_by="screener",
            screener=TRAINED),
        "agent_working": run("agent_working", "with_purpose", screener=STAND_IN),
        "agent_approved": run("agent_approved", "cat_meals_refreshments", route="agent_approve", **agent),
        "agent_flagged": run("agent_flagged", "cat_restricted_items", route="agent_flag", **agent),
        "guardrails_unsure": run(
            "guardrails_unsure", "cat_registrations_memberships", escalation_reasons=["unsure:OSU-GEN-06a"],
            **guardrails),
        "guardrails_low_confidence": run(
            "guardrails_low_confidence", "cat_clothing_ppe", escalation_reasons=["low_confidence:OSU-PRH-09a"],
            **guardrails),
        "agent_failed": run(
            "agent_failed", "cat_software_subscriptions", escalation_reasons=["agent_failed"], **guardrails),
        "lodging_stay_1": run("lodging_stay_1", "lodging_stay_1", route="agent_approve", **agent),
        "lodging_stay_2": run(
            "lodging_stay_2", "lodging_stay_2", trigger="late_receipt", replaces="lodging_stay_1",
            created_at=LATE_AT, route="human_review", decided_by="rerun", escalation_reasons=["review_conflict"]),
        "missing_document_1": run("missing_document_1", "missing_document_1", route="agent_approve", **agent),
        "missing_document_2": run(
            "missing_document_2", "missing_document_2", trigger="deadline", replaces="missing_document_1",
            created_at=DEADLINE_AT, route="flag", decided_by="rules"),
    }


def _field(ref: str, value, note: str | None = None) -> dict:
    return {"kind": "field", "ref": ref, "value": value, "note": note}


def _policy(ref: str, value=None, note: str | None = None) -> dict:
    return {"kind": "policy", "ref": ref, "value": value, "note": note}


def agent_outputs() -> dict[str, AgentOutput]:
    """The agent's answer for each run it finished, by run name, plus unresolved_citation, an
    answer that is valid JSON but cites a receipt line that doesn't exist (the guardrails must catch it).
    Low confidence below is 0.42; plan 16 sets the real threshold in the rules YAML."""

    def verdict(check_id: str, result: str, confidence: float, *evidence: dict) -> dict:
        return {"check_id": check_id, "result": result, "confidence": confidence, "evidence": list(evidence)}

    both_pass = [verdict("OSU-GEN-06a", "pass", 0.93), verdict("OSU-PRH-09a", "pass", 0.95)]
    answers = {
        "agent_approved": both_pass,
        "agent_flagged": [
            verdict("OSU-GEN-06a", "pass", 0.88),
            verdict(
                "OSU-PRH-09a", "fail", 0.91,
                _policy("OSU-PRH-09"),
                _field("transaction.merchant_norm", "PRAIRIE TROPHY AND AWARDS", "Plaques bought as staff service awards"),
            ),
        ],
        "guardrails_unsure": [
            verdict(
                "OSU-GEN-06a", "unsure", 0.55,
                _field("transaction.merchant_norm", "SOUTHWEST SOCIETY OF ENGINEERS", "Could be a student chapter"),
            ),
            verdict("OSU-PRH-09a", "pass", 0.9),
        ],
        "guardrails_low_confidence": [verdict("OSU-GEN-06a", "pass", 0.86), verdict("OSU-PRH-09a", "pass", 0.42)],
        "lodging_stay_1": both_pass,
        "missing_document_1": both_pass,
        "unresolved_citation": [
            verdict(
                "OSU-GEN-06a", "fail", 0.8,
                _policy("OSU-GEN-06"),
                {"kind": "receipt", "ref": "receipt.line_items[4]", "value": "12.00", "note": "No such line"},
            ),
            verdict("OSU-PRH-09a", "pass", 0.9),
        ],
    }
    return {name: AgentOutput.model_validate({"verdicts": verdicts}) for name, verdicts in answers.items()}


def flags(
    rules: RuleSet, runs: dict[str, DecisionRun], outputs: dict[str, AgentOutput]
) -> dict[str, tuple[Flag, ...]]:
    """Flags by run name. Code flags are listed here; agent flags are copied from the agent's
    fail and unsure verdicts, the way plan 16 will write them."""

    def flag(run_name: str, check_id: str, result: str, evidence, *, score=1.0, due_at=None) -> Flag:
        rule, check = rules.check(check_id)
        run = runs[run_name]
        return Flag(
            flag_id=fid("flag", f"{run_name}:{check_id}"),
            decision_id=run.decision_id,
            txn_id=run.txn_id,
            rule_id=rule.id,
            check_id=check_id,
            result=result,
            severity=rule.severity,
            evidence=evidence,
            score=score,
            source=check.method.value,
            due_at=due_at,
        )

    limit = Decimal(str(rules.rule("OSU-LIM-01").param("max_single_transaction"))).quantize(Decimal("0.01"))
    missing_receipt = _field("receipt", None, "missing input: receipt")
    found: dict[str, list[Flag]] = {
        "flag_over_limit": [
            flag("flag_over_limit", "OSU-LIM-01a", "fail", [
                _field("transaction.amount", str(limit + Decimal("0.01"))),
                _policy("params.max_single_transaction", str(limit), "Over by 0.01"),
            ]),
        ],
        "lodging_stay_1": [
            flag("lodging_stay_1", "OSU-GEN-04a", "pending", [missing_receipt], due_at=SIGNOFF),
            flag("lodging_stay_1", "OSU-TRV-07a", "not_evaluated", [missing_receipt]),
        ],
        "lodging_stay_2": [
            flag("lodging_stay_2", "OSU-TRV-07a", "fail", [
                {"kind": "receipt", "ref": "receipt.line_items[1]", "value": "30.06",
                 "note": "State and city lodging tax"},
                _policy("OSU-TRV-07"),
            ]),
        ],
        "missing_document_1": [
            flag("missing_document_1", "OSU-GEN-04a", "pending", [missing_receipt], due_at=SIGNOFF),
        ],
        "missing_document_2": [
            flag("missing_document_2", "OSU-GEN-04a", "fail", [
                _field("receipt", None, "no itemized receipt by cycle sign-off"),
                _policy("OSU-GEN-04"),
            ]),
        ],
    }
    for name, output in outputs.items():
        if name not in runs:
            continue
        for v in output.verdicts:
            if v.result is not AgentResult.PASS:
                result = "fail" if v.result is AgentResult.FAIL else "unclear"
                found.setdefault(name, []).append(flag(name, v.check_id, result, v.evidence, score=v.confidence))
    return {name: tuple(run_flags) for name, run_flags in found.items()}


def _pass(check_id: str) -> dict:
    return {"check_id": check_id, "result": "pass", "confidence": 0.9, "evidence": []}


# Agent answers the schema must reject, each with a fragment of the error it raises.
INVALID_AGENT_OUTPUTS: dict[str, dict] = {
    "fail_without_policy": {
        "error": "must include a policy citation",
        "output": {"verdicts": [{
            "check_id": "OSU-PRH-09a", "result": "fail", "confidence": 0.9,
            "evidence": [{"kind": "field", "ref": "transaction.amount", "value": "250.00"}],
        }]},
    },
    "unsure_without_evidence": {
        "error": "needs at least one citation",
        "output": {"verdicts": [{"check_id": "OSU-GEN-06a", "result": "unsure", "confidence": 0.5, "evidence": []}]},
    },
    "check_twice": {
        "error": "only once",
        "output": {"verdicts": [_pass("OSU-GEN-06a"), _pass("OSU-GEN-06a")]},
    },
    "unknown_field": {
        "error": "Extra inputs are not permitted",
        "output": {"verdicts": [_pass("OSU-GEN-06a") | {"reasoning": "Looks fine."}]},
    },
    "confidence_over_one": {
        "error": "less than or equal to 1",
        "output": {"verdicts": [_pass("OSU-GEN-06a") | {"confidence": 1.3}]},
    },
    "no_verdicts": {
        "error": "at least 1 item",
        "output": {"verdicts": []},
    },
}


def investigate_jobs(runs: dict[str, DecisionRun]) -> dict[str, InvestigateJob]:
    """One job per run the screener sent to the agent, keyed by run name."""
    return {
        name: InvestigateJob(decision_id=run.decision_id, snapshot_id=run.snapshot_id, check_ids=AGENT_CHECKS)
        for name, run in runs.items()
        if run.screener is not None and run.screener.sends_to_agent
    }


def read_receipt_jobs() -> dict[str, ReadReceiptJob]:
    return {name: ReadReceiptJob(receipt_id=r.receipt_id, txn_id=r.txn_id) for name, r in receipts().items()}


def review_outcomes(runs: dict[str, DecisionRun], found_flags: dict[str, tuple[Flag, ...]]) -> dict[str, ReviewOutcome]:
    def review(name: str, run_name: str, final: str, reviewer: str, reason: str, *,
               disagree: dict[str, str] | None = None, missed: tuple[str, ...] = ()) -> ReviewOutcome:
        disagree = disagree or {}
        per_flag = [
            {"flag_id": f.flag_id, "agree": f.check_id not in disagree, "note": disagree.get(f.check_id)}
            for f in found_flags.get(run_name, ())
        ]
        run = runs[run_name]
        return ReviewOutcome(
            review_id=fid("review", name),
            decision_id=run.decision_id,
            reviewer=reviewer,
            final=final,
            per_flag=per_flag,
            missed_rule_ids=missed,
            reason=reason,
            created_at=run.created_at + timedelta(hours=2),
        )

    return {
        "lodging_stay_1_review": review(
            "lodging_stay_1_review", "lodging_stay_1", "approve", "reviewer.a@example.edu",
            "Conference hotel stay. Folio to follow."),
        "lodging_stay_2_review": review(
            "lodging_stay_2_review", "lodging_stay_2", "flag", "reviewer.b@example.edu",
            "Folio shows Oklahoma lodging tax; the university is exempt."),
        "guardrails_unsure_review": review(
            "guardrails_unsure_review", "guardrails_unsure", "approve", "reviewer.a@example.edu",
            "Department membership.",
            disagree={"OSU-GEN-06a": "A professional society, not a student organization."}),
        "agent_flagged_review": review(
            "agent_flagged_review", "agent_flagged", "flag", "reviewer.b@example.edu",
            "Plaques bought as staff service awards.", missed=("OSU-PRH-10",)),
    }


def _json(data) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _dump(models: dict) -> dict:
    return {name: model.model_dump(mode="json") for name, model in models.items()}


def catalog(
    txns: dict[str, TxnSpec],
    specs: dict[str, SnapshotSpec],
    snaps: dict[str, CombinedExpenseSnapshot],
    runs: dict[str, DecisionRun],
    found_flags: dict[str, tuple[Flag, ...]],
    reviews: dict[str, ReviewOutcome],
) -> str:
    snapshot_name = {s.snapshot_id: n for n, s in snaps.items()}
    run_name = {r.decision_id: n for n, r in runs.items()}
    lines = [
        "# Fixtures",
        "",
        "Generated by `python -m flag_it.fixtures.build` from `src/flag_it/fixtures/build.py` and the rules YAML.",
        "Don't edit these files: change the builder and rebuild. Load them with `flag_it.fixtures`,",
        'for example `fixtures.snapshot("receipt_mismatch")` or `fixtures.flags("agent_flagged")`.',
        "",
        "## Snapshots",
        "",
        "| Name | Category | Amount | Receipt | Anomaly | About |",
        "|---|---|---|---|---|---|",
    ]
    for name, snap in snaps.items():
        p = snap.payload
        receipt = p.receipt.match_status.value if p.receipt else "none"
        anomaly = p.anomaly.status.value if p.anomaly.score is None else str(p.anomaly.score)
        about = specs[name].note or txns[specs[name].txn].note
        lines.append(f"| `{name}` | {p.category.category} | {p.transaction.amount} | {receipt} | {anomaly} | {about} |")
    lines += [
        "",
        "## Decision runs",
        "",
        "| Name | Snapshot | Trigger | Replaces | Route | Decided by | Flags |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, run in runs.items():
        replaces = f"`{run_name[run.replaces_decision_id]}`" if run.replaces_decision_id else ""
        route = run.route.value if run.route else "(agent working)"
        decided_by = run.decided_by.value if run.decided_by else ""
        run_flags = ", ".join(f"{f.check_id} {f.result.value}" for f in found_flags.get(name, ()))
        lines.append(
            f"| `{name}` | `{snapshot_name[run.snapshot_id]}` | {run.trigger.value} | {replaces} | {route} "
            f"| {decided_by} | {run_flags} |"
        )
    lines += ["", "## Review outcomes", "", "| Name | Run | Final | Reason |", "|---|---|---|---|"]
    for name, review in reviews.items():
        lines.append(f"| `{name}` | `{run_name[review.decision_id]}` | {review.final.value} | {review.reason} |")
    lines += [
        "",
        "## Agent outputs",
        "",
        "`agent_outputs.json` holds the agent's answer for each run it finished, keyed by run name, plus",
        "`unresolved_citation`, a valid answer whose receipt citation points at a line that doesn't exist.",
        "`agent_outputs_invalid.json` holds answers the schema must reject:",
        "",
    ]
    lines += [f"- `{name}`: fails with \"{case['error']}\"" for name, case in INVALID_AGENT_OUTPUTS.items()]
    lines += [
        "",
        "## Jobs",
        "",
        "`jobs.json` has an `investigate` job for each run the screener sent to the agent (keyed by run name),",
        "and a `read_receipt` job for each receipt (keyed by receipt name).",
        "",
    ]
    return "\n".join(lines)


def build(rules: RuleSet | None = None) -> dict[str, str]:
    """Every fixture file's text, by file name."""
    rules = rules or load_rules()
    txns, found_receipts = transactions(rules), receipts()
    specs, snaps = snapshot_specs(rules), snapshots(rules)
    runs, outputs = decision_runs(rules, snaps), agent_outputs()
    found_flags = flags(rules, runs, outputs)
    reviews = review_outcomes(runs, found_flags)
    return {
        "raw_transactions.json": _json(_dump({n: raw_transaction(n, s) for n, s in txns.items()})),
        "receipt_files.json": _json(_dump({n: receipt_file(n, r) for n, r in found_receipts.items()})),
        "snapshots.json": _json(_dump(snaps)),
        "decision_runs.json": _json(_dump(runs)),
        "flags.json": _json({n: [f.model_dump(mode="json") for f in fs] for n, fs in found_flags.items()}),
        "agent_outputs.json": _json(_dump(outputs)),
        "agent_outputs_invalid.json": _json(INVALID_AGENT_OUTPUTS),
        "jobs.json": _json({"investigate": _dump(investigate_jobs(runs)), "read_receipt": _dump(read_receipt_jobs())}),
        "review_outcomes.json": _json(_dump(reviews)),
        "catalog.md": catalog(txns, specs, snaps, runs, found_flags, reviews),
    }


def write(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in build().items():
        (directory / name).write_text(text)


def check(directory: Path) -> list[str]:
    """Problems with the files in directory: stale, missing, or not built by this module."""
    files = build()
    problems = [
        f"{name} differs from a fresh build"
        for name, text in files.items()
        if not (directory / name).exists() or (directory / name).read_text() != text
    ]
    problems += [
        f"{path.name} is not built by build.py"
        for path in sorted(directory.glob("*.json"))
        if path.name not in files
    ]
    return problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m flag_it.fixtures.build")
    parser.add_argument("--check", action="store_true", help="exit 1 if fixtures/ differs from a fresh build")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(fixtures_dir())
        if problems:
            sys.exit("fixtures/ is stale. Run: python -m flag_it.fixtures.build\n" + "\n".join(problems))
        return
    write(fixtures_dir())


if __name__ == "__main__":
    main()
