// The review queue: runs waiting for a person, oldest first.
import { getQueue } from "../api/client";
import type { DecisionRun, ReviewQueue } from "../api/types";
import { day, money, reasonLabel } from "../labels";
import { decisionHref } from "../route";
import { useLoad } from "../useLoad";

type Summary = NonNullable<ReviewQueue["summaries"]>[number];

/** The queue response carries each run's merchant and amount, so a row needs no request of its own. */
function QueueRow({ run, summary }: { run: DecisionRun; summary: Summary | undefined }) {
  return (
    <tr>
      <td>{day(run.created_at)}</td>
      <td>
        <a href={decisionHref(run.decision_id)}>{summary?.merchant ?? "(unknown)"}</a>
      </td>
      <td className="num">{summary ? money(summary.amount) : ""}</td>
      <td>
        <ul className="plain">
          {(run.escalation_reasons ?? []).map((reason) => (
            <li key={reason}>{reasonLabel(reason)}</li>
          ))}
        </ul>
      </td>
    </tr>
  );
}

export function QueuePage() {
  const queue = useLoad(getQueue, "queue");
  if (queue.state === "loading") return <p>Loading the queue…</p>;
  if (queue.state === "error") return <p role="alert">Couldn't load the queue: {queue.message}</p>;
  const items = queue.data.items;
  const summaries = new Map((queue.data.summaries ?? []).map((summary) => [summary.decision_id, summary]));
  return (
    <section>
      <h1>Waiting for review</h1>
      {items.length === 0 ? (
        <p>Nothing is waiting for review.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Since</th>
              <th>Merchant</th>
              <th className="num">Amount</th>
              <th>Why it needs a person</th>
            </tr>
          </thead>
          <tbody>
            {items.map((run) => (
              <QueueRow key={run.decision_id} run={run} summary={summaries.get(run.decision_id)} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
