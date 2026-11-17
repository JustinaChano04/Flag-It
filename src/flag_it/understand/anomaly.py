"""The anomaly baseline: how unusual is this amount for this cardholder, using only earlier purchases.

    score = 0.6745 * (amount - median) / max(MAD, mad_floor)

over the cardholder's purchases (amount > 0) dated before the scored transaction's date. The median
and MAD (median absolute deviation) are robust: a few odd past charges don't distort them.
"""

from collections.abc import Sequence
from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field

from flag_it.contracts.enums import AnomalyStatus
from flag_it.contracts.transactions import NormalizedTransaction
from flag_it.contracts.understand import AnomalyResult
from flag_it.db.connection import Conn

CONFIG_PATH = Path(__file__).with_name("anomaly.yaml")
SCALE = Decimal("0.6745")  # makes the score comparable to a standard z-score for normal data


class AnomalyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Annotated[str, Field(min_length=1)]
    min_history: Annotated[int, Field(ge=1)]
    mad_floor: Annotated[Decimal, Field(gt=0)]


def load_anomaly_config(path: Path = CONFIG_PATH) -> AnomalyConfig:
    return AnomalyConfig.model_validate(yaml.safe_load(path.read_text()))


def robust_z(amount: Decimal, history: Sequence[Decimal], mad_floor: Decimal) -> float:
    center = median(history)
    mad = median(abs(x - center) for x in history)
    return float(SCALE * (amount - center) / max(mad, mad_floor))


def as_of_for(txn: NormalizedTransaction) -> datetime:
    """Midnight UTC at the start of the transaction date. Only history before it is used."""
    return datetime.combine(txn.transaction_date, time.min, tzinfo=timezone.utc)


# The newest normalized row of each transaction (the same choice records.load_normalized_transaction
# makes), then only this cardholder's purchases before the date, excluding the scored transaction.
_HISTORY = """
SELECT amount FROM (
    SELECT DISTINCT ON (txn_id) txn_id, cardholder_id, amount, transaction_date
    FROM normalized_transaction
    ORDER BY txn_id, created_at DESC
) newest
WHERE cardholder_id = %s AND transaction_date < %s AND txn_id <> %s AND amount > 0
"""


def cardholder_history(conn: Conn, txn: NormalizedTransaction) -> list[Decimal]:
    rows = conn.execute(_HISTORY, (txn.cardholder_id, txn.transaction_date, txn.txn_id)).fetchall()
    return [row["amount"] for row in rows]


def score_anomaly(conn: Conn, txn: NormalizedTransaction, config: AnomalyConfig) -> AnomalyResult:
    history = cardholder_history(conn, txn)
    enough = len(history) >= config.min_history
    return AnomalyResult(
        txn_id=txn.txn_id,
        model_version=config.version,
        status=AnomalyStatus.SCORED if enough else AnomalyStatus.INSUFFICIENT_HISTORY,
        score=robust_z(txn.amount, history, config.mad_floor) if enough else None,
        history_length=len(history),
        as_of=as_of_for(txn),
    )
