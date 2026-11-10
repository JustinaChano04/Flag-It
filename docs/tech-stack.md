# Tech stack and model choices

This page lists what each component is built with and where it runs. It has one row for each component in `architecture.md`. The technology diagrams in `technology-architecture.md` are drawn from these tables.

How to use this page:

- Fill in the `TBD` cells as choices are made.
- Record the reason for each choice in `decisions.md`, not here.

**Status values:** `set` = decided, `lean` = leaning toward it, `TBD` = not decided.

## Components

| Component | Kind | Model or library | Runs on | Speed and volume needed | Status |
|---|---|---|---|---|---|
| Receipt reader | Off-the-shelf model | To be picked in a bake-off (see [below](#receipt-reader-bake-off)). Candidates run through Ollama with thinking turned off and JSON output forced to a schema: NuExtract3 (4B), Qwen3-VL 8B, Qwen3.5 9B, and Qwen3.8 27B if there is enough GPU memory. Qwen2.5-VL 7B is the baseline. donut-receipts-extract is included as a comparison that isn't a vision-language model. | GPU machine, as a queue worker | About 1k receipts a day. A few seconds per receipt is fine. | TBD |
| Receipt matching | Code | TBD | TBD | TBD | TBD |
| Categorizer | Trained model | LightGBM, using scikit-learn text features such as TF-IDF on the merchant name. CatBoost is tested alongside it (see [below](#categorizer-comparison)). | Inside the pipeline container, for both training and scoring | Well under 1 ms per row. Speed is not a concern at this volume. | lean |
| Anomaly detector | Statistical baseline first; a trained model only if needed | **Baseline:** a robust z-score for each cardholder, `0.6745 * (amount - median) / MAD`, computed over that cardholder's past spending up to the transaction time. It can also be split by category. Settings come from config: the score threshold (start near 3.5), the minimum history length (below it, return "insufficient history", not 0), and a MAD floor (so constant spending doesn't cause a divide by zero). **Second option:** Isolation Forest on the shared features, only if the baseline misses the anomalies we inject. It needs no labels. | Inside the pipeline container | Well under 1 ms per row | lean |
| Rule checks | Code | Python, reading rules from `osu_rules.yaml` | TBD | TBD | lean |
| Risk screener | Trained model | TBD | TBD, for both training and scoring | TBD | TBD |
| Investigation agent | LLM judge | A hosted API for v1, called through a client that works with any provider, so a self-hosted model can replace it later. Which model: TBD. | Queue worker on the laptop | TBD | lean |
| Agent tools | Code | Lookups for history, trips, and per diem rates | TBD | TBD | TBD |
| Guardrails | Code | TBD | TBD | TBD | TBD |

## System layers

These are the parts of the system that are not components in the logical view.

| Layer | Question it answers | Choice | Status |
|---|---|---|---|
| Input: UI | How does someone upload one transaction and receipt, and work the human review queue? | React + Vite | set |
| Input: batch API | How do batches of transactions come in? | FastAPI, with one endpoint for single transactions and one for batches | set |
| Normalization | Where do raw fields become the combined expense record? | Python: a Pydantic schema plus pure, versioned functions in the pipeline container | set |
| Queue and workers | Which steps run in the background, and how many queues are there? | Redis + Arq. Only the investigation agent and the receipt reader use a queue. Every other step runs directly. One worker image is used everywhere, and the `WORKER_STAGES` setting picks which steps it runs. | lean |
| Storage | Where do transactions, receipts, flags, and feedback live? | Postgres. Decision records are never edited, only added to, and hold the features, outputs, and versions. Review outcomes have their own table. | set |
| Feature layer | Where does each cardholder's spending history come from, for anomaly and split-purchase checks? | History totals are SQL queries in Postgres that take an "as of" time. Per-row changes are Python (pandas). Training and the pipeline share one `compute_features` function. There is no feature store. | set |
| Model serving | Where do models run, and which need a GPU? | Small models are scored directly inside the pipeline. The receipt reader runs on the GPU machine as a queue worker. Receipt files are in MinIO so both machines can read them. | lean |
| Training | Where are trained models built? | scikit-learn + LightGBM in plain scripts. Each model file is versioned and listed in a metadata table. No experiment-tracking platform. | set |
| Evals and CI gate | What stops a change from being merged? | GitHub Actions. A merge is blocked by failing unit tests or rule fixtures, model benchmark thresholds, the LLM judge eval set, or lint, type, and rules YAML checks. Until the benchmark and judge sets exist, those two only report. | set |
| Monitoring and drift | How do we notice that incoming data has changed? | Evidently, run on a schedule over the logged features and predictions. It covers data and prediction drift, and performance drift once review outcomes exist. Pandera checks inputs to the feature layer. LLM judge tracing with Langfuse or Phoenix may be added later. Build this once logging has data. | lean |
| Hosting | Where does each part run? | A laptop for the pipeline, database, queue, and UI. A separate GPU machine for the receipt reader. | set |
| Containers | How is Docker set up? | Docker Compose, one file per machine. The laptop file runs the pipeline, Postgres, Redis, MinIO, the API, and the UI. The GPU file runs the receipt-reader worker. A slim worker image covers the CPU and LLM steps, and the GPU image builds on it. | set |

## Receipt reader bake-off

Every candidate model is tested on the same set of labeled receipts. Record the exact model tag and quantization with every result.

What to measure:

- **Field accuracy:** exact match on total, date, and merchant. Report line-item recall separately.
- **Honest blanks:** how often unreadable fields are left empty. An empty value is better than a confident wrong one.
- **Arithmetic:** line items add up to the subtotal, and subtotal + tax + tip equals the total.
- **Agreement with the card:** the total and date match the card transaction.
- **Receipt condition:** results split by digital PDF, scan, phone photo, faded thermal paper, and tilted images.
- **Business impact:** how many receipts go through without a person, how many need manual review, and how many are wrongly auto-approved.
- **Regression check:** a fixed set of receipts rerun after every model or prompt change.

## Categorizer comparison

Train LightGBM and CatBoost on the same data split and compare:

- Macro-F1 (accuracy averaged evenly across categories)
- Recall on rare categories
- p95 latency for scoring one row

Switch to CatBoost only if it is clearly more accurate. The likeliest reason it would be is its built-in handling of merchant names, which have many distinct values.

## Guardrails for models

The core guardrail is in `architecture.md`: every decision either cites the rule it is based on or goes to human review. The full worksheet for guardrails and security is `security-and-guardrails.md`. When a choice there is settled, move it into the tables on this page.
