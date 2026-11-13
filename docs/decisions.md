# Decisions

This is a log of decisions that change the code or the tech stack. Each entry says what was decided, why, and what was rejected.

How to add an entry:

- Put the newest entry at the top.
- Keep each entry to a few lines.
- If a later decision changes an earlier one, say so in both entries.

## 2026-11-12: Shared fixtures are generated, committed, and checked

- **Decided:**
  - `fixtures/` is built by `src/flag_it/fixtures/build.py` from the contract models and the rules YAML. IDs are `uuid5` of each fixture's name, times are fixed, and amounts at a limit come from `params`. A test fails when the committed files differ from a fresh build, the same pattern as the schema check.
  - `flag_it.fixtures` loads them as validated, read-only models. `flag_it.fixtures.seed.seed(conn)` writes them all to an empty Postgres database through `flag_it.db.records`, so later plans can run against real rows before the pipeline exists. Plan 03 therefore depends on plan 02 as well as plan 01.
  - Decision runs carry the fixed constant `FIXTURE_RULES_VERSION`, not a hash of the rules YAML, so an unrelated rules edit never makes the staleness check fail.
  - Every fixture investigation sends the same two `llm` checks (`OSU-GEN-06a`, `OSU-PRH-09a`). Choosing the real set is plan 21's job.
  - The screener thresholds (`0.5`, `0.2`) and the low-confidence agent score (`0.42`) are constants in `build.py`, because their `params` don't exist yet. Plan 16 must move them to the rules YAML and rebuild the fixtures; nothing fails if it forgets.
- **Why:** Hand-written JSON drifts from the contracts and the rules, and every change would be edited by hand in many places. Generated files stay in step, and the check makes drift visible in review.
- **Rejected:** Hand-written JSON validated by a test. Builder functions only, with no JSON: the review app and non-Python tools can't read them.

## 2026-11-11: Database: Alembic with hand-written SQL, append-only by trigger

- **Decided:**
  - Migrations are Alembic revisions of hand-written SQL. Code talks to Postgres through psycopg 3 (sync API), with no ORM. `src/flag_it/db/records.py` has a save and load function per table, and tests round-trip every contract model through Postgres. Versions at the time: psycopg 3.3.8, Alembic 1.20.1, SQLAlchemy 2.1.8, Postgres 17.
  - Every table has triggers that reject `UPDATE`, `DELETE`, and `TRUNCATE`. They guard against application code and mistakes, not a privileged operator; separate owner and app roles are a later step. The one exception is `decision_run`: its `route`, `decided_by`, and `escalation_reasons` may be filled in once, from empty, when the agent finishes.
  - A `txn` table holds transaction identity, because intake returns `txn_id` before normalization runs. Normalized rows are keyed on `(txn_id, normalizer_version)`.
  - Reruns form one chain per transaction: one `initial` run, and each run replaced at most once. The current decision is the run nothing replaces. One run per snapshot. History is ordered by walking the chain, not by `created_at`.
  - A correction is a new row, never an edit. Results take a new version, a re-uploaded receipt gets a new `receipt_id`, a late receipt or deadline adds a rerun, and a reviewer's mistake is answered by a later review outcome. Correcting a wrong source row (`raw_transaction`) is not settled here: intake dedup on `(source, external_id)` and `(source_file, source_line_no)` would treat a corrected resubmission as a duplicate. Plan 11 decides how a correction is identified.
  - `docs/schema.dbml` is generated from the migrated database, and a test fails when it's stale.
  - Rows only the database uses (`ReceiptFile`, `StoredAgentVerdict`) are models in `src/flag_it/db/rows.py`, not contract records.
  - No `model_version` table yet. Nothing in this plan reads it, no table links to it, and an append-only table's shape is permanent. A decision run already stores the screener's version and threshold. The plan that trains the screener adds the table, with its link to `decision_run`.
  - `txn` is its own table, not a `txn_id` column on `raw_transaction`, because intake assigns the ID before the raw row's normalization exists and every later table points at one stable identity row.
  - Scores are `double precision`, not `real`, so they read back exactly. Receipt line items are a `jsonb` array on the extraction row.
  - Database tests run against real Postgres: skipped locally without `FLAG_IT_TEST_DATABASE_URL`, failing in CI without it.
- **Why:** Hand-written SQL keeps one definition of each record (the Pydantic model) plus the table. Triggers make "never edited" hold for every client, not just our code. The rerun keys stop two concurrent reruns from forking the history. A generated diagram can't drift, as the hand-written one had.
- **Rejected:**
  - SQLAlchemy Core tables with autogenerate: a second definition of every record.
  - Numbered SQL files with our own runner: we'd own the version table and have no downgrades.
  - A separate decision outcome table, so `decision_run` has no exception: more joins for every read of a run.
  - Finding the current run, or ordering history, by `created_at`: the caller sets it, so it can tie or run backwards.
  - Editing or deleting a wrong row in place: it defeats the audit trail. Corrections are new rows.
  - The `category` and MCC lookup tables from the old `schema.dbml`: categories come from the rules YAML, and the lookup belongs to the categorizer (plan 12).

## 2026-11-10: Details settled while building the contracts package

- **Decided:**
  - Flag `result` is exactly `fail`, `violation`, `unclear`, `pending`, or `not_evaluated`.
  - `rules_version` is `policy.version` plus the first 12 characters of the rules file's SHA-256 hash, so it changes whenever the file does.
  - Who may choose which route (`ROUTES_BY_DECIDER`) is part of the contract, not stage logic. Changing it is a contract change.
  - A code-check flag must score 1.0.
  - The API request and response bodies are defined in `src/flag_it/contracts/api.py` and listed in `contracts.md`.
  - Example records live in `src/flag_it/contracts/examples.py`, inside the package, so plan 03's fixtures can build on them.
  - The rules file path can be overridden with `FLAG_IT_RULES_PATH`, for containers that don't have the repo layout.
  - Pydantic is pinned to one exact version so the committed JSON Schemas are identical on every machine and in CI.
- **Why:** These turn rules from `contracts.md` into checks that fail at validation time instead of in production.
- **Rejected:** Leaving `result` open-ended ("and others"): stages would invent values. Keeping routing rules only in stage code: a stage could pick a route nobody agreed to.

## 2026-11-07: Dependencies in pyproject.toml

- **Decided:** Dependencies and package metadata live only in `pyproject.toml`, installed with `pip install -e ".[dev,explore]"`. `requirements.txt` is removed. Notebook-only packages are in the `explore` extra.
- **Why:** The `src/flag_it/` layout needs an installable package, which needs `pyproject.toml`. One file means nothing to keep in sync.
- **Rejected:** Keeping `requirements.txt` beside it (two lists to sync). A lock tool such as uv or pip-tools, for now.

## 2026-11-10: Contract changes from the plan 01 review

- **Decided:**
  - **Strict for input, tolerant for records.** API request bodies, the agent's output, and the rules YAML reject unknown fields. Saved and queued records ignore them, so a minor `CONTRACT_VERSION` bump doesn't break readers still on the older version.
  - **The version check compares against `main`.** CI fails if the schemas differ from `main` and `CONTRACT_VERSION` isn't higher. The export tool refuses to write when the manifest is missing, unless told it's the first export.
  - **Reruns are linked.** A decision run records `trigger` (`initial`, `late_receipt`, `deadline`) and `replaces_decision_id`. A rerun that disagrees with an earlier review is `decided_by: rerun`, with escalation reason `review_conflict`. Escalation reasons are a fixed list.
  - **Pending flags carry `due_at`,** so the deadline job can find overdue checks.
  - **The risk screener never creates flags.** It only routes. Flag `source` is `code` or `llm`.
  - **An agent `fail` or `unsure` must cite at least one piece of evidence.** A `fail` must also cite the policy.
  - **Batch intake validates each item separately,** and reports items by position (`index`), so one malformed item can't reject the batch.
  - **Receipt extractions are keyed by `receipt_id`,** so a re-uploaded receipt doesn't collide with the first one.
  - Intake accepts optional `mcc_code` and `business_purpose` now, rather than adding them later.
  - Transaction status ("open", "waiting", "decided") is worked out from the newest run, not stored. Plan 17 defines it.
- **Why:** Each one closes a gap the review found, which would have been costly to change once wave 1 builds on the contract.
- **Rejected:**
  - Rejecting unknown fields everywhere: every new field would be a major bump.
  - Finding a rerun's predecessor by timestamp: two reruns at once can race.
  - Screener flags tied to a placeholder rule: a flag must name a broken rule.
  - Storing transaction status on the run: runs never change.

## 2026-11-07: Reruns after review, and what gets a version stamp

- **Decided:**
  - When a transaction a person already reviewed is rerun (late receipt or deadline), the new run goes to `human_review` only if its route disagrees with the reviewer's final call. If they agree, the new route stands. This changes the 2026-11-05 contracts entry, which sent every such rerun to a person.
  - `CONTRACT_VERSION` is stamped only on JSON that is saved and read back later: the snapshot, queue jobs, and API responses. It is no longer a column on `decision_run`. This changes the 2026-11-05 contracts entry.
  - Renamed `merchant` to `merchant_name` in the raw transaction, and `cardholder` to `cardholder_id` in the normalized transaction.
- **Why:** A machine still never overrules a person silently, but a person isn't asked to confirm their own decision. Table columns are already kept in step by database migrations, so a stamp adds nothing there. The new names say what the fields hold.
- **Rejected:** Never forcing review on a rerun: a machine could reverse a person unnoticed. Dropping stamps entirely: old snapshots couldn't say which shape they use.

## 2026-11-05: Blockers for the implementation plans

- **Decided:**
  - **Hard failure:** a failed `code` check (result `fail` or `violation`) on a rule with severity `prohibited`, `conditional`, or `documentation`. `guidance` failures are recorded and the run continues. `pending` and `not evaluated` never stop a run.
  - **Deadlines:** a scheduled job finds transactions whose `pending` checks are past their deadline and starts a new snapshot and run, the same way a late receipt does.
  - **Screener threshold:** stored with each trained model version in the model metadata table, chosen at training time. Not in the rules YAML.
  - **Screener before labels exist:** a stand-in returns probability 1.0, so nothing is auto-approved and every transaction that passes the code checks goes to the agent.
  - **Agent tools in v1:** `cardholder_history`, `merchant_history`, and `policy_lookup`. All are read-only and take an `as_of` time. Every call is logged with an ID so `tool_result` citations can be checked. `per_diem_rate` comes once the GSA rate table is loaded. `trip_lookup` waits for travel records.
  - **Receipt matching:** v1 only verifies receipts uploaded against a known transaction. It compares total, date, and merchant within tolerances kept in a config file. `unmatched` means the reader couldn't read enough fields to compare.
  - **Anomaly score:** read by the screener (as a feature) and the agent (as context it may cite). Not read by rule checks. The agent can't flag on it alone: a flag must cite a rule.
  - **Layout:** one package, `src/flag_it/`, with a folder per stage (`contracts/`, `db/`, `intake/`, `understand/`, `decide/`, `review/`, `pipeline/`, `workers/`). `tests/` mirrors it, `fixtures/` is at the root, and the React app is in `web/`.
- **Why:** Deterministic failures need no judgment, so the agent adds nothing. One rerun mechanism covers both late receipts and deadlines. The threshold depends on the model, not the policy. Sending everything to the agent at first is safest and builds labels fastest. Each tool uses data we have. Matching stays reproducible. Rule checks stay pure policy. A folder per stage gives each wave 1 track its own files.
- **Rejected:**
  - Hard failure on `prohibited` only, or a per-rule `stops_run` field.
  - Rechecking `pending` checks inside the existing run: it would edit a run.
  - Holding decisions until deadlines pass.
  - The screener threshold in the rules YAML or in app config.
  - A heuristic screener score, or one trained on synthetic labels.
  - Matching loose receipts to transactions, or LLM-only matching.
  - An "unusual amount" rule check.
  - Separate packages per component, or a flat layout without `src/`.

## 2026-11-05: Data contracts and handoffs between stages

- **Decided:** `docs/contracts.md` is the single contract for records, handoffs, and APIs. `data.md` keeps only facts about the data.
  - Each decision run reads one saved `combined_expense_snapshot` that never changes. All Decide stages, queue jobs, and the decision run point to it by `snapshot_id`. This replaces the plan for the decision record to keep its own frozen copy.
  - Queue jobs carry IDs only. Workers read from and write to Postgres.
  - Routes are `flag`, `auto_approve`, `agent_approve`, `agent_flag`, and `human_review`. "Approve or flag" means the agent decided, with citations.
  - All code checks run and every failure is recorded. A hard failure then routes to `flag` and skips the screener and the agent.
  - A flag's `severity` comes from the rule in the rules YAML. `score` is a confidence from 0 to 1. `evidence` is a list of typed citations that the guardrails can check.
  - The agent returns one verdict per `llm` check (`pass`, `fail`, or `unsure`). The guardrails send the run to a person on `unsure`, low confidence, an unresolved citation, or invalid output.
  - Intake is async and deduplicated on `(source, external_id)`. In a batch, each item succeeds or fails on its own.
  - A transaction without a receipt is decided right away. A receipt that arrives later starts a new snapshot and a new run. If a person already reviewed the old run, the new run goes to a person. (Changed on 2026-11-07: only if the new run disagrees with the reviewer.)
  - There is one semver `CONTRACT_VERSION`. The generated JSON Schemas are committed, and CI fails if they change without a version bump. (Changed on 2026-11-07: stamped only on saved JSON, not on `decision_run`.)
  - A review outcome records the final call, agreement with each flag, missed rules, and a reason.
- **Why:** Snapshots keep every stage on the same input and make the decision auditable. Sending IDs keeps Postgres the only place data lives. Per-check verdicts and typed citations let the guardrails verify answers mechanically. The review fields give labels for the screener and the judge evaluation.
- **Rejected:**
  - Rebuilding the combined expense in each stage: stages can disagree.
  - Full payloads in queue messages: messages go stale.
  - Stopping at the first failed check: reviewers see only one reason.
  - A single overall agent verdict: it can't be traced to a specific rule.
  - Waiting for receipts, or requiring them at intake.
  - A version number for each record: more bookkeeping than this project needs.

## 2026-10-24: Use Evidently for drift instead of hand-written statistics

- **Decided:** Drift (changes in incoming data over time) is measured with Evidently. A scheduled script reads the logged features and predictions and compares them with a reference snapshot saved at training time. Pandera checks inputs to the feature layer. Logging is built first. The monitoring script is built once there is enough logged history.
- **Why:** The drift tests are standard and already exist in Evidently. Our real work is choosing which features to watch and when to alert. The script works on DataFrames, so it needs no extra service.
- **Rejected:**
  - Writing our own PSI and KS tests.
  - whylogs: we already store the raw features.
  - NannyML, for now. Revisit it for the risk screener while labels are scarce.
  - Prometheus and Grafana for drift. They may still be used for operational metrics.
  - LLM judge tracing with Langfuse or Phoenix is postponed.
- **Open:** Check the current Evidently version and API before building. This choice was made from prior knowledge, not checked against current docs.

## 2026-10-24: MinIO, one compose file per machine, and the CI gate

- **Decided:**
  - Receipts are stored in MinIO (which uses the S3 API), behind the storage interface, so both machines can reach them.
  - Each machine has its own Docker Compose file. The laptop runs the pipeline, Postgres, Redis, MinIO, the API, and the UI. The GPU machine runs the receipt-reader worker, pointed at the laptop's services.
  - GitHub Actions runs the CI gate, with Postgres and Redis as service containers.
  - A merge is blocked by any of these: failing unit tests or rule fixtures; a model doing worse on a frozen benchmark; the LLM judge eval set; lint, type checks, or rules YAML validation (including no reused or renumbered IDs).
- **Why:** The GPU worker needs the same receipts as the laptop, and using MinIO now avoids a code change later. One compose file per machine matches how the hardware is actually split, without the overhead of an orchestrator. The gate covers all three kinds of logic: deterministic checks, trained models, and the judge.
- **Rejected:**
  - A shared network drive: fragile across machines.
  - Fetching receipts through the API: the GPU worker would stop whenever the API is down.
  - One compose file with profiles.
  - k3s: too much overhead for two machines.
- **Risk to watch:** The judge eval blocks merges, but its results vary between runs and each run costs API calls. To manage this: keep the set small and fixed, pin the model version, allow a tolerance instead of requiring an exact match, and run it only when prompts, tools, rules, or the judge client change. If it keeps failing at random, make it report-only.
- **Open:** The model benchmark and the judge eval set don't exist yet. Until they do, those parts of the gate only report.

## 2026-10-24: Normalization and features in Python and SQL, with no feature store

- **Decided:**
  - Normalization is Pydantic models plus pure, versioned functions, running in the pipeline container.
  - History totals (rolling spend, how often a merchant is used, time since the last purchase) are SQL queries in Postgres that take an "as of" time. Training, the pipeline, and the agent tools all use the same queries.
  - Per-row changes are Python (pandas).
  - Training and the pipeline share one `compute_features` function. It returns a flat dict, which is logged with a feature-set version.
- **Why:** The main risks are features computed differently in training and production, and training on data from the future. One shared feature function and "as of" queries prevent both. At this volume, nothing needs a separate service.
- **Rejected:**
  - A feature store (Feast, Tecton): more than we need.
  - Spark and Flink.
  - dbt, for now.
  - DuckDB can be added later for training and drift scripts if history queries get slow. Polars is a preference, not a need.

## 2026-10-24: FastAPI and React, receipts on a volume, ML in plain scripts

- **Decided:**
  - FastAPI for the API (endpoints for one transaction and for batches) and for the review app's backend.
  - React + Vite for the review app.
  - Receipt files on a local volume, with their paths in Postgres. They sit behind a storage interface, so an S3-compatible store (MinIO) can replace the volume later.
  - The three trained models use scikit-learn and LightGBM in plain training scripts. Model files are versioned and listed in a metadata table. No experiment-tracking platform.
- **Why:** FastAPI is Python and supports async, like the workers. The storage interface makes the later move to object storage a config change. Plain scripts are enough for three small models at this volume.
- **Rejected:**
  - Django and Flask: heavier, or weaker at async.
  - HTMX and Streamlit: weaker for a review workflow.
  - MinIO from the start: one more container before it was needed.
  - MLflow: one more service to run.
  - Fine-tuning a Hugging Face model for the categorizer. Revisit if merchant names turn out too messy for TF-IDF.
- **Partly replaced:** Receipts now go to MinIO from the start, not a local volume. See "MinIO, one compose file per machine, and the CI gate".

## 2026-10-24: Postgres, a swappable LLM client, a separate GPU machine, and a web review app

- **Decided:**
  - Postgres is the main database. It holds transactions, decision records (only ever added to, never edited, with features, outputs, and versions), and review outcomes.
  - The investigation agent calls the LLM through one client interface. v1 uses a hosted API, and a self-hosted open model can replace it later.
  - The system runs on a laptop plus a separate GPU machine. The receipt reader is the GPU work.
  - Human review happens in a small web app.
- **Why:** Workers on different machines need a database they can reach over the network. Postgres also handles JSON feature logs and later drift queries. The client interface means changing the judge's provider is a config change. The review app is where reviewers' decisions are captured as labels for the screener and for drift monitoring.
- **Rejected:**
  - SQLite: works on one machine only.
  - DuckDB or Parquet as the main store: weak when several writers work at once. Fine later for analytics.
  - Hard-wiring one LLM provider.
  - Reviewing in a notebook or on the command line: no clean way to capture feedback.

## 2026-10-24: A real queue for the slow steps only, and one worker image

- **Decided:**
  - A Redis-backed queue (Arq) for the investigation agent, and probably the receipt reader.
  - The fast steps (matching, categorizer, anomaly detector, rule checks, risk screener, guardrails) run directly, as batch function calls in one pipeline process.
  - One worker codebase, with a registry of step handlers. The `WORKER_STAGES` setting picks which steps each deployment runs.
  - A job carries only the transaction ID and the step. Transaction status and decision records stay in the database. Every step can safely run twice.
- **Why:** Only the LLM judge and the receipt reader are slow, rate-limited, or likely to fail. Volume is about 1k transactions a day, with spikes at month end, so the queue is for retries, backoff, and isolating failures, not for speed. A real queue also gives delayed retries and a dead-letter queue without writing that logic ourselves.
- **Rejected:**
  - A queue for each model: adds delay and new ways to fail to steps that take milliseconds.
  - A Postgres job table: simpler, but we'd have to write the retry and job-claiming logic ourselves.
  - Kafka and RabbitMQ: far more than this volume needs.
  - A worker autoscaler: a fixed number of workers is enough. Revisit if GPU machines are rented on demand.

## 2026-10-24: Synthetic data is test data, kept separate from the real dataset

- **Decided:** Generate pass, fail, and boundary test cases for the `code` checks from the rule `params`. Build them by adding violations to real rows, not by inventing whole transactions. Anomaly test data is a separate set, built later.
- **Why:** The public data has no correct answers attached, so a rule that never fires looks the same as a broken one. Test cases generated from `params` stay in step with the policy.
- **Rejected:**
  - Adding test cases to the real dataset itself: mixes test data with the baseline.
  - Waiting until after the architecture to build synthetic data: then there's no way to tell engine bugs from rule bugs.
