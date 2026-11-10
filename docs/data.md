# Data

This page describes the data Flag-It uses: the real transactions we test on and the synthetic test data we still need to build. The records each stage produces are in [contracts.md](contracts.md).

Rules and checks are documented in `policies/README.md`, not here.

## Terms used on this page

| Term | Meaning |
|---|---|
| P-card | Purchasing card: a university-issued card for business expenses. |
| MCC | Merchant category code. The card network's label for the kind of business a merchant is (for example, a restaurant or an airline). |
| Check | One automated test of a rule. Each check has a type: `code` (deterministic), `model` (statistical or trained), or `llm` (judged by a language model). |
| Flag | A check result that needs reporting, such as a rule violation. |
| Cardholder | The person the card belongs to. The public data has no card ID, so we approximate it (see `cardholder` in [contracts.md](contracts.md#normalized-transaction)). |

## Real data

We test on public Oklahoma p-card transactions. They are real, but they are missing several things the checks need.

- **Notebook:** `data_exploration/ok_pcard_exploration.ipynb`
- **MCC lookup:** `data_exploration/mcc_to_category.csv`
- **Fields:** see [Raw transaction](contracts.md#raw-transaction).

What the data does not have:

- Receipts
- Business purposes (the cardholder's reason for the purchase)
- Card IDs
- 4-digit MCC codes (only the text label is included)

The item text that is included is cut off at about 50 characters, and is often generic (`GENERAL PURCHASE`).

**What this means:** `llm` checks and checks that need a receipt cannot be tested on this data. The [Synthetic data plan](#synthetic-data-plan) covers how we test them instead.

## Spend categories

Each transaction gets one spend category. The category decides which rules apply to it.

`data_exploration/mcc_to_category.csv` maps every MCC label found in the OSU rows to one of these 15 categories:

- Equipment & tools
- Services, shipping & fees
- Airfare & baggage
- Office & general supplies
- Lodging
- Registrations & memberships
- Meals & refreshments
- Lab, research & medical supplies
- Software & subscriptions
- Utilities & facilities
- Ground transportation
- Clothing & PPE
- Restricted items
- Parking & tolls
- Other / unclear (MCCs that no rule covers yet)

## Data contracts

The records each pipeline stage produces, the handoffs between stages, and the APIs are in [contracts.md](contracts.md). Field definitions for the raw export are under [Raw transaction](contracts.md#raw-transaction).

## Synthetic data plan

The real data can't test every check, so we build three test sets.

| Set | What it tests | How it is built | How results are measured |
|---|---|---|---|
| Rule fixtures | Each `code` check fires on a violation, stays quiet otherwise, and handles edge cases at the thresholds. | Real rows with violations added. Thresholds come from `params` in the rules YAML. | Table-driven tests: each row lists the check it should trigger. |
| Anomaly set | Unusual spending that the deterministic checks miss. | Real rows with anomalies of known size added. | Precision at K: of the K highest-scored transactions, how many are real anomalies. |
| LLM / receipt set | Checks that read the business purpose or a receipt. | Not decided yet. Needs item descriptions and receipts. | Its own evaluation set, built after the `code_screen` and `decision` criteria are reviewed. |

**Rule for every fixture row:** record which check it targets and the expected outcome.

## Open questions

- Is there a better public data source than OSU? Record the answer here once settled.
- Which fields need to be added, if any, for checks that read `transaction` and `table:<name>`?
