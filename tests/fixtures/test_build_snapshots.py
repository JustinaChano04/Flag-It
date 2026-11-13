"""Fixture snapshots: with and without receipts, each match status, and two rerun chains."""

from decimal import Decimal

from flag_it.contracts.enums import AnomalyStatus, LineType, MatchStatus
from flag_it.fixtures.build import RECEIPT_TXN, fid, receipt_file, receipts, snapshots


def test_every_spend_category_has_a_snapshot(rules):
    assert {s.payload.category.category for s in snapshots(rules).values()} == set(rules.categories)


def test_snapshots_with_and_without_receipts_and_history(rules):
    snaps = snapshots(rules).values()
    assert any(s.payload.receipt is None for s in snaps)
    assert {s.payload.receipt.match_status for s in snaps if s.payload.receipt} == set(MatchStatus)
    assert any(s.payload.anomaly.status is AnomalyStatus.INSUFFICIENT_HISTORY for s in snaps)


def test_ids_are_unique_and_stable(rules):
    snaps = snapshots(rules)
    assert len({s.snapshot_id for s in snaps.values()}) == len(snaps)
    for name, snap in snaps.items():
        assert snap.snapshot_id == fid("snapshot", name)


def test_chain_snapshots_share_their_parts_except_the_receipt(rules):
    snaps = snapshots(rules)
    for txn in ("lodging_stay", "missing_document"):
        first, second = snaps[f"{txn}_1"].payload, snaps[f"{txn}_2"].payload
        assert (first.transaction, first.category, first.anomaly) == (second.transaction, second.category, second.anomaly)
        assert snaps[f"{txn}_1"].created_at < snaps[f"{txn}_2"].created_at
    assert snaps["lodging_stay_1"].payload.receipt is None
    assert snaps["lodging_stay_2"].payload.receipt is not None


def test_the_late_folio_has_an_oklahoma_tax_line_and_matches_the_charge(rules):
    folio = receipts()["lodging_stay_folio"]
    assert any(item.line_type is LineType.TAX for item in folio.line_items)
    assert folio.total == snapshots(rules)["lodging_stay_2"].payload.transaction.amount


def test_line_items_add_up(rules):
    for receipt in receipts().values():
        if receipt.total is not None:
            assert sum(Decimal(i.amount) for i in receipt.line_items) == receipt.total


def test_receipt_files_point_at_their_transactions():
    for name, receipt in receipts().items():
        file = receipt_file(name, receipt)
        assert (file.receipt_id, file.txn_id) == (receipt.receipt_id, fid("txn", RECEIPT_TXN[name]))
