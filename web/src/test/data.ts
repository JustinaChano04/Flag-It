// Test data from the shared fixtures (fixtures/*.json at the repo root), so the UI is tested
// against the same records the Python tests use.
import { vi } from "vitest";
import decisionRuns from "../../../fixtures/decision_runs.json";
import flagsByRun from "../../../fixtures/flags.json";
import reviewOutcomes from "../../../fixtures/review_outcomes.json";
import snapshots from "../../../fixtures/snapshots.json";
import type { CombinedExpenseSnapshot, DecisionRun, Flag, ReviewDetail, ReviewOutcome } from "../api/types";

const runs = decisionRuns as unknown as Record<string, DecisionRun>;
const flags = flagsByRun as unknown as Record<string, Flag[]>;
const reviews = Object.values(reviewOutcomes as unknown as Record<string, ReviewOutcome>);
const snaps = Object.values(snapshots as unknown as Record<string, CombinedExpenseSnapshot>);

export const run = (name: string): DecisionRun => runs[name];

/** What GET /decisions/{id} would return for a fixture run (cited rules are made up). */
export function detail(name: string): ReviewDetail {
  const r = run(name);
  const chain = [r];
  while (chain[chain.length - 1].replaces_decision_id) {
    const previous = Object.values(runs).find((x) => x.decision_id === chain[chain.length - 1].replaces_decision_id);
    if (!previous) break;
    chain.push(previous);
  }
  const ids = new Set(chain.map((x) => x.decision_id));
  const runFlags = flags[name] ?? [];
  return {
    run: r,
    snapshot: snaps.find((s) => s.snapshot_id === r.snapshot_id)!,
    flags: runFlags,
    agent_verdicts: [],
    rules: [...new Set(runFlags.map((f) => f.rule_id))].map((rule_id) => ({
      rule_id,
      title: `Title of ${rule_id}`,
      text: `Text of ${rule_id}.`,
      severity: "prohibited",
      source_section: "Section",
      source_page: "19",
    })),
    history: chain,
    reviews: reviews.filter((review) => ids.has(review.decision_id)),
  };
}

type Handler = (init?: RequestInit) => { status?: number; body: unknown };

/** Replace fetch: each key is "METHOD /api/path". An unexpected request fails the test. */
export function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const handler = routes[key];
    if (!handler) throw new Error(`unexpected request: ${key}`);
    const { status = 200, body } = handler(init);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
