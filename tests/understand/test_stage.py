"""understand() saves both results once; calling it again returns the saved ones."""

from decimal import Decimal

from flag_it.contracts.enums import AnomalyStatus
from flag_it.contracts.examples import TXN_ID, normalized
from flag_it.contracts.rules import load_rules
from flag_it.db import records
from flag_it.db.examples import save_example_transaction
from flag_it.understand.anomaly import AnomalyConfig
from flag_it.understand.categorize import load_lookup
from flag_it.understand import stage
from flag_it.understand.categorize import categorize
from flag_it.understand.stage import understand
from tests.understand.test_anomaly import save_history

CONFIG = AnomalyConfig(version="robust-z-test", min_history=10, mad_floor=Decimal("1.00"))


def test_both_results_are_saved(conn):
    save_example_transaction(conn)
    lookup = load_lookup(load_rules())
    category, anomaly = understand(conn, normalized(), lookup, CONFIG)
    assert records.load_category_result(conn, TXN_ID, lookup.version) == category
    assert records.load_anomaly_result(conn, TXN_ID, CONFIG.version) == anomaly
    assert category.category == "meals_refreshments"


def test_a_second_call_returns_the_saved_results_unchanged(conn):
    save_example_transaction(conn)
    lookup = load_lookup(load_rules())
    first = understand(conn, normalized(), lookup, CONFIG)
    assert first[1].status is AnomalyStatus.INSUFFICIENT_HISTORY
    save_history(conn)  # history that arrives later doesn't rewrite a saved result
    assert understand(conn, normalized(), lookup, CONFIG) == first


def test_a_concurrent_run_that_saves_first_wins_without_an_error(conn, monkeypatch):
    save_example_transaction(conn)
    lookup = load_lookup(load_rules())

    def categorize_while_another_run_saves(txn, lookup):
        result = categorize(txn, lookup)
        records.save_category_result(conn, result)  # the other run's save lands first
        return result

    monkeypatch.setattr(stage, "categorize", categorize_while_another_run_saves)
    category, _ = understand(conn, normalized(), lookup, CONFIG)
    assert records.load_category_result(conn, TXN_ID, lookup.version) == category
