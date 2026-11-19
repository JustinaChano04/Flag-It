// The review: final call, agreement with each flag, rules the system missed, and a reason.
import { useState, type FormEvent } from "react";
import { ApiError, postReview } from "../api/client";
import type { Flag, ReviewFinal, ReviewIn } from "../api/types";
import { loadReviewer, saveReviewer } from "../reviewer";

type Answer = { agree: boolean | null; note: string };

/** "OSU-LIM-01, OSU-TRV-13" -> ["OSU-LIM-01", "OSU-TRV-13"]. The server checks each one. */
export function parseRuleIds(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((id) => id.trim().toUpperCase()).filter(Boolean))];
}

export function ReviewForm({ decisionId, flags }: { decisionId: string; flags: Flag[] }) {
  const [reviewer, setReviewer] = useState(loadReviewer);
  const [final, setFinal] = useState<ReviewFinal | null>(null);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [missed, setMissed] = useState("");
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  const answer = (flagId: string): Answer => answers[flagId] ?? { agree: null, note: "" };
  const setAnswer = (flagId: string, change: Partial<Answer>) =>
    setAnswers((all) => ({ ...all, [flagId]: { ...answer(flagId), ...change } }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!final) return;
    const body: ReviewIn = {
      reviewer: reviewer.trim(),
      final,
      per_flag: flags
        .filter((flag) => answer(flag.flag_id).agree !== null)
        .map((flag) => ({
          flag_id: flag.flag_id,
          agree: answer(flag.flag_id).agree as boolean,
          note: answer(flag.flag_id).note.trim() || null,
        })),
      missed_rule_ids: parseRuleIds(missed),
      reason: reason.trim() || null,
    };
    setSending(true);
    setProblems([]);
    try {
      await postReview(decisionId, body);
      saveReviewer(body.reviewer);
      setSaved(true);
    } catch (error) {
      setProblems(error instanceof ApiError && error.problems.length ? error.problems : [String((error as Error).message)]);
    } finally {
      setSending(false);
    }
  }

  if (saved) {
    return (
      <p role="status">
        Review saved. <a href="#/">Back to the queue</a>
      </p>
    );
  }

  const unanswered = flags.filter((flag) => answer(flag.flag_id).agree === null).length;
  return (
    <form className="review" onSubmit={submit}>
      <h2>Your review</h2>
      <label>
        Your name <input required value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
      </label>

      {flags.map((flag) => (
        <fieldset key={flag.flag_id}>
          <legend>{flag.check_id}: is this flag right?</legend>
          <label>
            <input type="radio" name={`agree-${flag.flag_id}`} checked={answer(flag.flag_id).agree === true}
              onChange={() => setAnswer(flag.flag_id, { agree: true })} /> Agree
          </label>
          <label>
            <input type="radio" name={`agree-${flag.flag_id}`} checked={answer(flag.flag_id).agree === false}
              onChange={() => setAnswer(flag.flag_id, { agree: false })} /> Disagree
          </label>
          <label>
            Note <input value={answer(flag.flag_id).note} onChange={(e) => setAnswer(flag.flag_id, { note: e.target.value })} />
          </label>
        </fieldset>
      ))}

      <label>
        Rules the system missed (IDs such as OSU-LIM-01)
        <input value={missed} onChange={(e) => setMissed(e.target.value)} />
      </label>
      <label>
        Reason <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>

      <fieldset>
        <legend>Final call</legend>
        <label>
          <input type="radio" name="final" checked={final === "approve"} onChange={() => setFinal("approve")} /> Approve
        </label>
        <label>
          <input type="radio" name="final" checked={final === "flag"} onChange={() => setFinal("flag")} /> Flag
        </label>
      </fieldset>

      {unanswered > 0 && <p className="meta">{unanswered} flag(s) not answered yet.</p>}
      {problems.length > 0 && (
        <ul role="alert" className="problems">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
      <button type="submit" disabled={!final || !reviewer.trim() || sending}>
        {sending ? "Saving…" : "Save review"}
      </button>
    </form>
  );
}
