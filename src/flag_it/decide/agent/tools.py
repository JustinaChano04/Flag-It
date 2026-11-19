"""The agent's v1 tools and the ledger of its calls (contracts.md "Agent tools").

All tools are read-only and bound to the snapshot's transaction: the model chooses only a limit, a
merchant text, or a rule ID, never a cardholder or a time, so it cannot see another cardholder's
data or anything from after the transaction. A good call is recorded in the ledger under the ID
the model's call carried; the guardrails later check that a `tool_result` citation names a recorded
call, and that a `history` citation names a recorded query and `as_of`. A failed call is not
recorded, so it cannot be cited. The ledger lives for one job.

Arguments are checked in Python before any SQL runs, and each call runs in a savepoint, so a SQL
error cannot abort the job's database transaction. Merchant text in a result was written by third
parties, so it is fenced like the transaction's own text.
"""

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from flag_it.contracts.rules import RuleSet
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.db.connection import Conn
from flag_it.decide.agent.llm import ToolResult, ToolSpec, ToolUse
from flag_it.decide.agent.prompt import fence
from flag_it.understand.anomaly import as_of_for

log = logging.getLogger(__name__)

TOOL_NAMES = ("cardholder_history", "merchant_history", "policy_lookup")
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


@dataclass(frozen=True)
class LedgerEntry:
    call_id: str
    tool: str
    arguments: Mapping[str, Any]
    history_ref: str | None


class ToolLedger:
    def __init__(self) -> None:
        self._entries: dict[str, LedgerEntry] = {}

    def record(self, call_id: str, tool: str, arguments: Mapping[str, Any], history_ref: str | None = None) -> LedgerEntry:
        entry = LedgerEntry(call_id, tool, dict(arguments), history_ref)
        self._entries[call_id] = entry
        return entry

    def has(self, call_id: str) -> bool:
        return call_id in self._entries

    def has_history(self, ref: str) -> bool:
        return any(entry.history_ref == ref for entry in self._entries.values())

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries.values())


def _digest(arguments: Mapping[str, Any]) -> str:
    """Short hash of a call's arguments, so a history citation names the query and not just the tool."""
    return hashlib.sha256(json.dumps(dict(arguments), sort_keys=True, default=str).encode()).hexdigest()[:8]


SPECS = (
    ToolSpec(
        "cardholder_history",
        "This cardholder's earlier purchases (before this transaction), newest first: merchant, amount, date.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT}},
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "merchant_history",
        "How often this cardholder's agency has bought from a merchant before this transaction. "
        "With no merchant, uses this transaction's merchant.",
        {"type": "object", "properties": {"merchant": {"type": "string"}}, "additionalProperties": False},
    ),
    ToolSpec(
        "policy_lookup",
        "The full text, source section and checks of one rule, by rule ID (for example OSU-PRH-09).",
        {
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
            "required": ["rule_id"],
            "additionalProperties": False,
        },
    ),
)

# The newest normalized row of each transaction, then only this cardholder's earlier purchases,
# excluding the transaction being judged (the same choice the anomaly detector makes).
_NEWEST = """
    SELECT DISTINCT ON (txn_id) txn_id, agency_id, cardholder_id, merchant_norm, amount, transaction_date, mcc_code
    FROM normalized_transaction ORDER BY txn_id, created_at DESC
"""
_CARDHOLDER_HISTORY = f"""
SELECT merchant_norm, amount, transaction_date, mcc_code FROM ({_NEWEST}) newest
WHERE cardholder_id = %s AND transaction_date < %s AND txn_id <> %s
ORDER BY transaction_date DESC, txn_id LIMIT %s
"""
_MERCHANT_HISTORY = f"""
SELECT count(*) AS visits, coalesce(sum(amount), 0) AS total_amount,
       min(transaction_date) AS first_seen, max(transaction_date) AS last_seen
FROM ({_NEWEST}) newest
WHERE cardholder_id = %s AND agency_id = %s AND merchant_norm = %s AND transaction_date < %s AND txn_id <> %s
"""


class ToolBox:
    def __init__(self, conn: Conn, snapshot: CombinedExpenseSnapshot, rules: RuleSet, ledger: ToolLedger) -> None:
        self._conn, self._rules, self._ledger = conn, rules, ledger
        self._txn = snapshot.payload.transaction
        self._as_of = as_of_for(self._txn)

    def specs(self) -> tuple[ToolSpec, ...]:
        return SPECS

    def call(self, use: ToolUse) -> ToolResult:
        try:
            # A savepoint: a failed query rolls back to here and leaves the job's transaction usable.
            with self._conn.transaction():
                if use.name == "cardholder_history":
                    body, history = self._cardholder_history(use.arguments), True
                elif use.name == "merchant_history":
                    body, history = self._merchant_history(use.arguments), True
                elif use.name == "policy_lookup":
                    body, history = self._policy_lookup(use.arguments), False
                else:
                    return ToolResult(use.id, f"unknown tool {use.name!r}", True)
        except Exception as error:  # a bad call is an answer for the model, not a failed job
            log.warning("tool %s failed: %s", use.name, error)
            return ToolResult(use.id, f"{type(error).__name__}: {error}", True)
        ref = f"{use.name}@{self._as_of.isoformat()}#{_digest(use.arguments)}" if history else None
        if ref is not None:
            body["history_ref"] = ref
        self._ledger.record(use.id, use.name, use.arguments, ref)
        return ToolResult(use.id, json.dumps(body, default=str))

    def _cardholder_history(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be a whole number from 1 to {MAX_LIMIT}")
        rows = self._conn.execute(
            _CARDHOLDER_HISTORY, (self._txn.cardholder_id, self._txn.transaction_date, self._txn.txn_id, limit)
        ).fetchall()
        return {"transactions": [{**row, "merchant_norm": fence(row["merchant_norm"])} for row in map(dict, rows)]}

    def _merchant_history(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        merchant = arguments.get("merchant", self._txn.merchant_norm)
        if not isinstance(merchant, str) or not merchant.strip():
            raise ValueError("merchant must be a non-empty string")
        row = self._conn.execute(
            _MERCHANT_HISTORY,
            (self._txn.cardholder_id, self._txn.agency_id, merchant, self._txn.transaction_date, self._txn.txn_id),
        ).fetchone()
        return {"merchant": fence(merchant), **dict(row)}

    def _policy_lookup(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        rule_id = arguments.get("rule_id")
        if not isinstance(rule_id, str):
            raise ValueError("rule_id must be a string")
        try:
            rule = self._rules.rule(rule_id)
        except KeyError:
            raise ValueError(f"no rule {rule_id!r}") from None
        return {
            "rule_id": rule.id,
            "title": rule.title,
            "text": rule.text,
            "severity": rule.severity.value,
            "source": {"section": rule.source.section, "page": rule.source.page},
            "checks": [{"id": check.id, "ask": check.ask} for check in rule.checks],
        }
