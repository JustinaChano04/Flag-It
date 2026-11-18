# Decisions

This is a log of decisions that change the code or the tech stack. Each entry says what was decided, why, and what was rejected.

How to add an entry:

- Put the newest entry at the top.
- Keep each entry to a few lines.
- If a later decision changes an earlier one, say so in both entries.

## 2026-11-16: Rule checks: only certain evidence fails; deployed inputs; word lists in the rules YAML; a billing calendar

- **Decided:**
  - `run_rule_checks` runs every applicable `code` check on a snapshot and returns flags. A check that needs an input the deployment doesn't have (listed in `src/flag_it/decide/checks/inputs.yaml`, today `transaction` and `receipt`) is skipped with no flag. A deployed input missing for one transaction gives `not_evaluated`. For a `document_presence` check, the missing document is itself the finding: `pending` before its deadline, `fail` after.
  - **Only certain evidence fails a check.** Certain evidence is `fail` (a hard failure for any severity except guidance). Suggestive evidence is `unclear`: never a hard failure, but `needs_review` is set and the run can't be auto-approved. A blank receipt field is `not_evaluated`, because the reader may have missed it.
  - Line-item checks read three word lists from the rule's `params`: `<name>_terms` (certain), `<name>_review_terms` (ambiguous), and `<name>_except_terms` (phrases that cancel a match). Matching is on whole words, ignoring case and punctuation. Lodging lines are recognized by `line_type: room` before any word. Every list has tests for innocent lines that share its words ("Special Interest Group dues", "Meeting room rental"). The lists are drafted from the rule text and need the same human review as the rest of the YAML.
  - The receipt total may differ from the charge by `total_tolerance` (0.50, the same as receipt matching); a tip on the receipt may explain the rest; a charge higher than a receipt with no tip is `unclear` (a tip may have been added after printing). Percentages are compared exactly.
  - New check `OSU-GEN-04c` reports a receipt whose `match_status` is `mismatch` as `unclear`, as contracts.md's "a mismatch is a finding" requires. Other checks don't read a mismatched receipt's lines, since it may not be this charge's receipt. The receipt-total check (`OSU-GEN-04b`) still compares the two, but on a mismatched receipt it only ever needs review, so a receipt that may belong to another charge never causes a hard failure. Plan 13's matcher counts a tip read on the receipt, so ordinary tipped meals match.
  - 15 checks are implemented. 13 more can't be decided from today's inputs and report `not_evaluated` with the reason, listed in `registry.py`: 12 need receipt facts the extraction doesn't hold (merchant or rental location, delivery dates, service terms, prepayment), and `OSU-SPL-01a` needs the cardholder's other charges. A test keeps the two lists covering every deployable check.
  - A checker that raises gives `not_evaluated` ("checker error") and is logged; the other checks still run.
  - Billing cycles and sign-off cutoffs come from `policies/osu/billing_cycles.yaml`, because the Pcard accountant sets each cutoff (Pcard Guidelines p. 14-15). A transaction belongs to the cycle containing its post date. A deadline in a cycle the file doesn't list gives `not_evaluated`. The file ships empty until real cutoffs are added.
  - "Now" is the snapshot's `created_at`, and a flag's ID is `uuid5(decision_id, check_id)`, so running one snapshot for one run twice gives the same flags.
  - **Later, in order:** (1) the receipt reader tags each line's kind (`alcohol`, `penalty`, ...) from a fixed list, a contract change made with plan 13's bake-off; a reader tag that agrees with the words is certain, and one that disagrees needs review. (2) The agent judges `unclear` lines with the line cited (plan 16). (3) Once reviews exist (plan 17), a labeled set of receipt lines gates every check that can hard-fail on precision in CI, and words that reviewers keep overruling move from `_terms` to `_review_terms`.
- **Why:** A hard failure skips the screener and the agent, so a wrong one flags an innocent purchase with no second look. Words are ambiguous ("interest", "room"), so a word alone may only send a run to be looked at, and certain words are kept separate. Flagging every input the deployment never has would add 17 to 22 `not_evaluated` flags to each transaction, and reviewers would learn to ignore them. Word lists and tolerances are policy content like limits, so they belong next to their rule, and a new policy stays mostly YAML. A fixed sign-off offset would encode a date the guidelines don't set.
- **Rejected:**
  - Every word match as a hard failure (the first draft of this plan; plan review found "Special Interest Group dues" and "Meeting room rental" flagged outright).
  - Every word match only as a review: clear violations ("bartending", "late fee") would cost an agent call each.
  - A `not_evaluated` flag for every missing input, deployed or not.
  - Word lists in a config file next to the code: it splits one rule's meaning across two files.
  - A sign-off date computed as a fixed number of days after the cycle ends.
  - One generic checker per pattern: the YAML's `ask` is prose, not a machine-readable condition.
  - Adding location, delivery date, term, and prepayment fields to the receipt extraction now: a contract change, and a change to plan 13's reader before its bake-off.

## 2026-11-12: Categorizer is the MCC lookup for now; anomaly baseline settings

- **Decided:**
  - Plan 12 builds only the lookup categorizer. The trained categorizer gets its own plan once labeled categories exist.
  - The lookup key ignores case, spacing, and punctuation, so "EATING PLACES, RESTAURANTS" and the export's "EATING PLACES  RESTAURANTS" match. It matched every OSU row of the January 2025 export.
  - Lookup confidence labels map to `high` 0.9, `medium` 0.7, `low` 0.5, `unmapped` 0.0. An MCC not in the file is `other_unclear` with 0.0. The lookup version is `lookup-` plus the first 12 characters of the file's SHA-256 hash.
  - The anomaly baseline uses the cardholder's purchases (amount > 0) dated before the transaction date, taking each transaction's newest normalized row. `min_history` is 10 and the MAD floor is $1.00, in `src/flag_it/understand/anomaly.yaml`, versioned `robust-z-1`. The score threshold is not a setting here: the screener and the agent read the score.
  - `understand()` returns a result already saved for the same version instead of computing it again. If a concurrent run saves the same result first, that one is kept and returned. An MCC the lookup doesn't know is logged, so it gets added.
  - Known gaps, from the 2026-11-16 plan review: results are keyed on `(txn_id, version)` without the normalizer version, so after a normalizer change `understand()` would return the old category and score; this must be fixed (fold the normalizer version into the result version, or a contract change) before the first `NORMALIZER_VERSION` bump. `anomaly.yaml`'s version is bumped by hand, unlike the lookup's hash. A score reflects the history known when it was computed (`history_length` shows how much).
- **Why:** A model trained on the lookup's own labels would only learn the lookup's mistakes. A hash version can't drift from the file. Refunds would pull the median down and make normal purchases look unusual. Reusing saved results keeps the stage safe to retry with append-only tables.
- **Rejected:**
  - Training LightGBM on high-confidence lookup rows as weak labels.
  - Failing on an unknown MCC: one new MCC would stop the pipeline.
  - A hand-written lookup version string: it can drift from the file's content.
  - Including refunds in the anomaly history.
## 2026-11-12: Receipts: upload, reader behind a setting, and matching tolerances

- **Decided:**
  - Plan 13 owns the receipt upload endpoint, the storage interface (`ReceiptStore`: MinIO in production, a local folder in tests), and the MinIO Compose service.
  - The reader model is a setting (`FLAG_IT_READER_MODEL`, default `qwen3-vl:8b-q4_K_M`) until the bake-off picks one. Ollama is called with thinking off, temperature 0, and the output forced to an all-text schema. Text the code can't parse is saved empty. Unreadable output after one retry is a blank reading with `match_status: unmatched`.
  - PDFs are sent as PNG images of their first 3 pages.
  - Matching: `unmatched` when the total is unreadable, or both the date and the merchant are. Otherwise `mismatch` when a readable field is outside its tolerance: total within $0.50 of the charge (by absolute value, so refunds compare), or total plus a tip read on the receipt within $0.50, date within 3 days, merchant similarity at least 0.6 after cleaning (1.0 when one name contains the other).
  - A repeated `read_receipt` job for a receipt the same reader model already read returns the saved extraction without reading again, so plan 21 can still start the late-receipt rerun after a crash. Jobs are queued with the ID `read_receipt:<receipt_id>`, and a duplicate running at the same time keeps the first saved extraction.
  - A job seen before its upload commits raises `ReceiptNotReady`, a subclass of Arq's `Retry`, so Arq runs it again 5 seconds later. Arq 0.28 retries nothing else: any other exception fails the job for good.
  - Uploads accept PDF, JPEG, and PNG up to 10 MB, and the file's first bytes must match its declared type. A file that still can't be decoded, or an image over 25 million pixels, is saved as a blank `unmatched` reading with the reason logged; huge PDF pages are rendered smaller. Unreadable model output is logged before it is discarded.
  - `match_status` is saved with the reading and is not recomputed when `matching.yaml` changes; the row doesn't record which tolerances produced it. This is acceptable while the tolerances are untuned. Before they are tuned after the bake-off, a contract change adds the matcher's version to `receipt_extraction`, so old and new results can be told apart and re-matched.
  - Later, with the bake-off: the reader also tags each line's kind (`alcohol`, `penalty`, `postage`, ...) from a fixed list taken from the rules, so plan 14's line checks have stronger evidence than words (see the 2026-11-16 rule-checks decision). It is a contract change.
- **Why:** The bake-off needs labeled receipts that don't exist yet, and a setting lets it choose without a code change. An all-text schema keeps a misread amount from arriving as a float. Tolerances in a file make matching reproducible and easy to tune after the bake-off.
- **Rejected:**
  - Running the bake-off before building the worker: it would block the receipt track on collecting receipts.
  - Asking the model for numbers: floats are refused as money, and a guessed number looks as confident as a read one.
  - Committing the upload before queueing the job: tests would leave committed rows behind; the retry handles the race instead.
  - Raising a plain exception for "not ready" and leaving the retry to plan 21's wrapper: until that wrapper exists, receipts would silently never be read.
  - Trusting the declared content type: the bytes go to a PDF parser written in C.

## 2026-11-12: Intake normalizes in the request; receipt upload belongs to plan 13

- **Decided:**
  - Intake validates and normalizes each item inside the request, then saves the raw row, `txn`, and the normalized row in one savepoint. It still answers `202`. An invalid item stores nothing. FastAPI 0.163.1.
  - `normalize` is a pure function with `NORMALIZER_VERSION`. Merchant cleanup and the cardholder key are ported from the exploration notebook. A last name with no letters is invalid, not merged into a shared key. An amount with fractions of a cent is invalid, not rounded. Dates are `dd-MON-yy` (the export) or ISO (API clients).
  - A concurrent submit of the same `(source, external_id)` ends as `duplicate`: the losing insert's unique violation is caught and the item is looked up again.
  - An amount must be a plain decimal: exponents, NaN, Infinity, and currency signs are invalid. A missing field is reported as "required". Invalid items and lost races are logged.
  - Known gaps, from the 2026-11-16 plan review: a corrected resubmission with the same `(source, external_id)` is a `duplicate`, so correcting a source row isn't supported; it needs a correction marker in the intake API (a contract change), deferred until real corrections appear. File rows are deduplicated by file name and line number only, so the same export saved under two names loads twice (`data/raw/ok_pcard_2025-01.csv` and `data/raw/fy2025/pcard_public_202501.csv` are identical), and a charge sent through the API and loaded from a file becomes two transactions. Load each month once, from `data/raw/fy*/`. The loader loads every agency in the export; which agencies are reviewed is plan 21's decision.
  - The monthly export loader keeps every file row as a raw row and gives a `txn_id` only to rows that normalize. File rows are identified by `(file name, line number)`.
  - The API app is `src/flag_it/api.py`, which only mounts each stage's router. `get_conn` in `src/flag_it/deps.py` gives each request one connection that commits on success.
  - The receipt upload endpoint and receipt storage belong to plan 13, with the rest of the receipt work.
- **Why:** Normalizing in the request is the only way to report unreadable values as `invalid`, and it is too fast to need a queue. One savepoint per item keeps the batch rule (one bad item never rejects the others). Keeping unreadable file rows raw means a fixed normalizer can process them later without reloading files.
- **Rejected:**
  - Normalizing in the background: the client couldn't be told an amount is unreadable.
  - Rounding sub-cent amounts: silently changes money.
  - Giving a `txn_id` to file rows that can't be normalized: every later stage would have to handle a transaction with no normalized row.

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
  - A `txn` table holds transaction identity, because intake returns `txn_id` before normalization runs. Normalized rows are keyed on `(txn_id, normalizer_version)`. (Changed 2026-11-12: intake now normalizes in the request. The `txn` table still separates identity from normalized rows, and file rows that can't be normalized stay raw with no `txn_id`.)
  - Reruns form one chain per transaction: one `initial` run, and each run replaced at most once. The current decision is the run nothing replaces. One run per snapshot. History is ordered by walking the chain, not by `created_at`.
  - A correction is a new row, never an edit. Results take a new version, a re-uploaded receipt gets a new `receipt_id`, a late receipt or deadline adds a rerun, and a reviewer's mistake is answered by a later review outcome. Correcting a wrong source row (`raw_transaction`) is not settled here: intake dedup on `(source, external_id)` and `(source_file, source_line_no)` would treat a corrected resubmission as a duplicate. Plan 11 deferred it: a corrected resubmission is a duplicate until the intake API gets a correction marker (see 2026-11-12).
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
