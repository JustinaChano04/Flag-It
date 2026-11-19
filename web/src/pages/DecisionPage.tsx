// One decision run with everything a reviewer reads, and the review form.
import { getDecision, receiptFileUrl } from "../api/client";
import type { Citation, CitedRule, Flag, ReceiptExtraction, ReviewDetail } from "../api/types";
import { ReviewForm } from "../components/ReviewForm";
import { day, money, reasonLabel, RESULT_LABEL, ROUTE_LABEL } from "../labels";
import { decisionHref } from "../route";
import { useLoad } from "../useLoad";

function Evidence({ items }: { items: Citation[] }) {
  return (
    <ul className="evidence">
      {items.map((c, i) => (
        <li key={i}>
          <code>{c.ref}</code>
          {c.value != null && <> = {String(c.value)}</>}
          {c.note && <span className="note"> — {c.note}</span>}
        </li>
      ))}
    </ul>
  );
}

function FlagCard({ flag, rule }: { flag: Flag; rule?: CitedRule }) {
  return (
    <article className={`flag result-${flag.result}`}>
      <h3>
        <span className="pill">{RESULT_LABEL[flag.result]}</span> {flag.check_id}
        {rule && <> · {rule.title}</>}
      </h3>
      <p className="meta">
        {flag.severity} · from {flag.source}
        {flag.due_at && <> · due {day(flag.due_at)}</>}
      </p>
      {rule && (
        <blockquote>
          {rule.text} <cite>({rule.source_section}, p. {rule.source_page})</cite>
        </blockquote>
      )}
      <Evidence items={flag.evidence} />
    </article>
  );
}

function Receipt({ receipt }: { receipt: ReceiptExtraction }) {
  return (
    <section className="card">
      <h2>Receipt</h2>
      <p>
        Match: <strong>{receipt.match_status}</strong> · read by <code>{receipt.reader_model}</code>
      </p>
      <div className="receipt">
        <iframe title="Receipt file" src={receiptFileUrl(receipt.receipt_id)} />
        <table>
          <tbody>
            <tr><th>Merchant</th><td>{receipt.merchant ?? "(blank)"}</td></tr>
            <tr><th>Date</th><td>{receipt.receipt_date ?? "(blank)"}</td></tr>
            {(receipt.line_items ?? []).map((line, i) => (
              <tr key={i}>
                <td>{line.description ?? "(blank)"} <span className="meta">{line.line_type}</span></td>
                <td className="num">{money(line.amount)}</td>
              </tr>
            ))}
            <tr><th>Subtotal</th><td className="num">{money(receipt.subtotal)}</td></tr>
            <tr><th>Tax</th><td className="num">{money(receipt.tax)}</td></tr>
            <tr><th>Tip</th><td className="num">{money(receipt.tip)}</td></tr>
            <tr><th>Total</th><td className="num">{money(receipt.total)}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Detail({ detail }: { detail: ReviewDetail }) {
  const { run, snapshot, flags } = detail;
  const { transaction: txn, category, anomaly, receipt } = snapshot.payload;
  const rules = new Map((detail.rules ?? []).map((rule) => [rule.rule_id, rule]));
  return (
    <>
      <section className="card">
        <div className="summary">
          <h1>{txn.merchant_norm}</h1>
          <span className="amount">{money(txn.amount)}</span>
          {run.route ? (
            <span className={`badge route-${run.route}`}>{ROUTE_LABEL[run.route]}</span>
          ) : (
            <span className="badge route-human_review">The agent is still working</span>
          )}
        </div>
        <p className="meta">
          {run.decided_by && <>decided by {run.decided_by} · </>}
          {run.trigger.replace("_", " ")} run of {day(run.created_at)}
        </p>
        {(run.escalation_reasons ?? []).length > 0 && (
          <ul className="reasons">
            {(run.escalation_reasons ?? []).map((reason) => (
              <li key={reason} className="chip">{reasonLabel(reason)}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Transaction</h2>
        <table>
          <tbody>
            <tr><th>Cardholder</th><td>{txn.cardholder_id}</td></tr>
            <tr><th>Date</th><td>{txn.transaction_date} (posted {txn.post_date})</td></tr>
            <tr><th>Merchant category</th><td>{txn.mcc_description}</td></tr>
            <tr><th>Business purpose</th><td>{txn.business_purpose ?? "(none given)"}</td></tr>
            <tr><th>Spend category</th><td>{category.category} ({Math.round(category.confidence * 100)}% sure)</td></tr>
            <tr>
              <th>Unusual for this cardholder?</th>
              <td>
                {anomaly.status === "scored"
                  ? `score ${anomaly.score?.toFixed(1)} over ${anomaly.history_length} earlier purchases`
                  : `not enough history (${anomaly.history_length} earlier purchases)`}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      {receipt ? <Receipt receipt={receipt} /> : <p>No receipt has been uploaded.</p>}

      <section className="card">
        <h2>Flags ({flags.length})</h2>
        {flags.length === 0 && <p>No check flagged anything.</p>}
        {flags.map((flag) => (
          <FlagCard key={flag.flag_id} flag={flag} rule={rules.get(flag.rule_id)} />
        ))}
      </section>

      {(detail.agent_verdicts ?? []).length > 0 && (
        <section>
          <h2>The agent's verdicts</h2>
          {(detail.agent_verdicts ?? []).map((verdict) => (
            <article key={verdict.check_id} className="flag">
              <h3>
                <span className="pill">{verdict.result}</span> {verdict.check_id} · {Math.round(verdict.confidence * 100)}% confident
              </h3>
              <Evidence items={verdict.evidence ?? []} />
            </article>
          ))}
        </section>
      )}

      {detail.history.length > 1 && (
        <section>
          <h2>Runs of this transaction</h2>
          <ol>
            {detail.history.map((past) => (
              <li key={past.decision_id}>
                {past.decision_id === run.decision_id ? (
                  <strong>this run</strong>
                ) : (
                  <a href={decisionHref(past.decision_id)}>{day(past.created_at)} {past.trigger.replace("_", " ")}</a>
                )}
                {": "}
                {past.route ? ROUTE_LABEL[past.route] : "agent working"}
              </li>
            ))}
          </ol>
        </section>
      )}

      {(detail.reviews ?? []).length > 0 && (
        <section>
          <h2>Earlier reviews</h2>
          <ul>
            {(detail.reviews ?? []).map((review) => (
              <li key={review.review_id}>
                {day(review.created_at)}: {review.reviewer} said <strong>{review.final}</strong>
                {review.decision_id !== run.decision_id && " (on an earlier run)"}
                {review.reason && <>: “{review.reason}”</>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {run.route ? (
        <ReviewForm decisionId={run.decision_id} flags={flags} />
      ) : (
        <p>This run can be reviewed once the agent has finished.</p>
      )}
    </>
  );
}

export function DecisionPage({ decisionId }: { decisionId: string }) {
  const detail = useLoad(() => getDecision(decisionId), decisionId);
  if (detail.state === "loading") return <p>Loading…</p>;
  if (detail.state === "error") return <p role="alert">Couldn't load this run: {detail.message}</p>;
  return <Detail detail={detail.data} />;
}
