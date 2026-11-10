# Guardrails and security worksheet

This worksheet lists the guardrails and security controls the system needs, and tracks which are decided. The approach: design as if the data were real, but run only on public and synthetic data.

How to use it:

1. Fill in the `TBD` cells.
2. Move each settled choice into `tech-stack.md`.
3. Record the reason in `decisions.md`.

**Status values:** `set` = decided, `lean` = leaning toward it, `TBD` = not decided.

**Scope values:** `build` = will be implemented, `design` = documented only, not built.

## 1. Guardrails

**Core principle:** when a model fails, the transaction gets more scrutiny, never an approval.

Guardrails sit at three points: when data comes in, after each model, and at the final decision.

### 1.1 Input guards

These check data as it enters the system.

| Guard | What it checks | Where it runs | Scope | Status |
|---|---|---|---|---|
| Schema validation | Correct types, required fields present, values in sensible ranges (for example, negative amounts or future dates) | API and normalization, using Pydantic | build | TBD |
| Feature checks | Missing values, out-of-range values, categories never seen before, values far outside the usual range | Before the feature layer, using Pandera | build | TBD |
| Quarantine | A record that fails is set to `rejected` or `needs_review`, with the reason. It is never filled in with guessed values and passed to a model. | Pipeline status tracking | build | TBD |
| Prompt-injection defense | Text from receipts, merchant names, and descriptions is treated as data, never as instructions, when it goes into the judge's prompt | Judge client | build | TBD |

Open questions:

- Which free-text fields reach an LLM prompt? TBD
- Should the judge only have read-only tools? TBD
- How is untrusted text marked off in the prompt so the model treats it as data? TBD

### 1.2 Model output guards

Each model can fail in its own way. This table says how each failure is caught and where the transaction goes next.

| Model | How it can fail | How it is caught | Where it goes next | Status |
|---|---|---|---|---|
| Receipt reader | Reads the receipt wrong, such as the wrong total or date | Output must match the extraction schema. The total and date are compared with the card transaction. Low confidence is reported as "receipt unreadable". | Human review | TBD |
| Categorizer | Returns a category not in the policy, or has low confidence | Output must be one of the listed categories and meet a confidence threshold | Investigation agent or a person | TBD |
| Anomaly detector | A new cardholder has no history to compare against | A minimum history length. Below it, return "insufficient history", not 0. | The risk screener treats it as higher risk | TBD |
| Risk screener | Gives a badly calibrated score, or sees input unlike its training data | Scores must be calibrated probabilities. Unfamiliar input is sent on rather than approved. | Investigation agent | TBD |
| LLM judge | Returns malformed output, makes up a rule, or invents evidence | Output must match a strict schema. Every `rule_id` it cites must exist in the rules YAML. Every piece of evidence it quotes must appear in the transaction or receipt. On a format error it gets one retry, then the transaction is escalated. | Human review | TBD |

Thresholds still to choose (they are read from config, not written into code): categorizer confidence, the screener's escalation threshold, minimum history length, and how far the receipt and card amounts may differ. TBD

### 1.3 Decision guards

These are written in code. No model can override them.

| Guard | Rule | Status |
|---|---|---|
| Hard rules win | Neither the screener nor the judge can override a broken hard rule. | TBD |
| Judge can't clear a flag | If the rules flagged a transaction, the judge cannot approve it. It can only add flags or escalate. | TBD |
| High-dollar check | Above $X, a transaction is always investigated. X is TBD. | TBD |
| Cite or escalate | Every decision cites a rule (an approval cites the checks that passed), or goes to a person. | TBD |
| Audit sampling | A random share of auto-approvals goes to human review. The share is TBD. | TBD |
| Circuit breaker | If escalations, errors, or judge failures suddenly spike, auto-approval stops and everything goes to review. Triggers and limits are TBD. | TBD |

## 2. Security

### 2.1 What we protect and where it is exposed

**What we protect:** transactions, receipts (images and PDFs), decision records with their logged features, review outcomes, and API keys.

A trust boundary is a point where data passes between parts of the system that trust each other differently. Each one needs its own control.

| Boundary | Data that crosses it | Main threat | Control | Status |
|---|---|---|---|---|
| User to API | Uploads and batch files | Malformed, malicious, or oversized files | Size and type limits, validation, authentication | TBD |
| Receipt text to LLM | Untrusted text inside a prompt | Prompt injection | See 1.1, plus a test set of attack examples | TBD |
| Pipeline to hosted LLM | Transaction and receipt content | Sensitive data leaving the system | Send as little as possible, redact it, check how long the provider keeps data, keep a self-hosted fallback | TBD |
| Laptop to GPU machine | Receipts, jobs, results | Eavesdropping, services that accept anyone | Private network, TLS, authentication on each service | TBD |
| Between services | Postgres, Redis, and MinIO traffic | Open ports, default passwords | Private network only, real credentials, nothing exposed publicly | TBD |
| Review app to reviewer | Transaction and receipt views | Someone without permission viewing data | Login and roles | TBD |

### 2.2 Controls

PII is personally identifiable information. A PAN is a full card number.

| Area | Control | Scope | Choice | Status |
|---|---|---|---|---|
| Keep less PII | Mask card numbers when data comes in and never store full PANs. Replace cardholder IDs with pseudonyms. | build | TBD | TBD |
| Redact before the LLM | Remove identifiers before building prompts. A test fails the build if raw PII reaches a prompt or log. | build | TBD | TBD |
| Logs and reports | No raw PII in logs, decision records, or monitoring reports | build | TBD | TBD |
| Secrets | Environment variables or a secrets manager. No secrets in the repo or in images. | build | TBD | TBD |
| Secret scanning | A scanner runs in CI | build | Candidate: gitleaks (check the current version) | TBD |
| Dependency scanning | A vulnerability scan runs in CI | build | Candidates: pip-audit, Trivy (check them) | TBD |
| Dependency pinning | Exact versions, with hashes | build | TBD | TBD |
| Safe model files | Use safe file formats, or trusted sources checked by hash. Never load arbitrary pickle files. | build | TBD | TBD |
| Network | A private network between machines | build | Candidates: Tailscale, local network | TBD |
| Transport | TLS between machines | build | TBD | TBD |
| Service login | Redis password or access lists, Postgres roles, MinIO keys | build | TBD | TBD |
| App login | Local accounts or an OIDC provider | build | TBD | TBD |
| Roles | Reviewer and admin | build | TBD | TBD |
| Audit log | Records who viewed or changed review outcomes | build | TBD | TBD |
| Retention | A written retention period and a job that deletes old data | build | Period: TBD | TBD |
| Encryption at rest and key management | Beyond the defaults | design | TBD | TBD |
| Single sign-on | Enterprise login | design | TBD | TBD |
| Compliance mapping | Which controls support PCI-DSS, SOC 2, and GDPR. No compliance is claimed. | design | TBD | TBD |

### 2.3 Questions to settle

- Will this ever see real company data, or only public and synthetic data? TBD
- Is the hosted LLM acceptable for anything other than public data? TBD
- Will the review app have one user or many? TBD
- Local accounts or an OIDC provider? TBD
- What should the one-page threat model cover beyond the table in 2.1? TBD

## 3. Tests to add to the CI gate

| Test | What it proves | Status |
|---|---|---|
| Prompt-injection set | Receipts and descriptions that say things like "approve this" don't change the decision. | TBD |
| PII leak test | Raw PII never reaches a prompt, log, or decision record. | TBD |
| Judge output check | Judge answers that are malformed, cite no rule, or cite a made-up rule are escalated. | TBD |
| Guard order | The judge cannot approve a transaction that a hard rule flagged. | TBD |
| Circuit breaker | A simulated spike stops auto-approval. | TBD |
| Secret and dependency scans | No leaked secrets and no dependencies with known vulnerabilities. | TBD |

## 4. Limits of these claims

This project shows the controls and the reasons for them. It is not a security review or a compliance certification. Every doc that describes security should say so.
