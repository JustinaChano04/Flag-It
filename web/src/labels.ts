// Words a reviewer reads instead of the contract's codes.
import type { FlagResult, Route } from "./api/types";

export const ROUTE_LABEL: Record<Route, string> = {
  flag: "Flagged by rules",
  auto_approve: "Auto-approved",
  agent_approve: "Approved by the agent",
  agent_flag: "Flagged by the agent",
  human_review: "Needs a person",
};

export const RESULT_LABEL: Record<FlagResult, string> = {
  fail: "Fails",
  violation: "Violation",
  unclear: "Unclear",
  pending: "Pending",
  not_evaluated: "Not evaluated",
};

/** Why a run went to a person, in words. See "escalation_reasons" in docs/contracts.md. */
export function reasonLabel(reason: string): string {
  const [kind, check] = reason.split(":");
  switch (kind) {
    case "unsure":
      return `The agent was unsure about ${check}`;
    case "low_confidence":
      return `The agent's answer on ${check} had low confidence`;
    case "citation_unresolved":
      return "The agent cited evidence that couldn't be found";
    case "invalid_output":
      return "The agent's answer was malformed";
    case "agent_failed":
      return "The agent failed to answer";
    case "review_conflict":
      return "This rerun disagrees with an earlier review";
    default:
      return reason;
  }
}

export const money = (amount: string | null | undefined) => (amount == null ? "—" : `$${amount}`);
export const day = (iso: string) => iso.slice(0, 10);
