// The review API, as the UI calls it. Paths start with /api; Vite's dev server forwards them.
import type { ReviewDetail, ReviewIn, ReviewOutcome, ReviewQueue, TransactionView } from "./types";

export const API_BASE = "/api";

/** A response that wasn't 2xx. `problems` lists each field error of a 422, readable as is. */
export class ApiError extends Error {
  readonly status: number;
  readonly problems: string[];

  constructor(status: number, message: string, problems: string[] = []) {
    super(message);
    this.status = status;
    this.problems = problems;
  }
}

type ErrorBody = { detail?: string | { loc?: (string | number)[]; msg: string }[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE + path, init);
  if (response.ok) return (await response.json()) as T;
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // not JSON: report the status alone
  }
  const detail = body.detail;
  if (Array.isArray(detail)) {
    const problems = detail.map((d) => `${(d.loc ?? []).filter((part) => part !== "body").join(".")}: ${d.msg}`);
    throw new ApiError(response.status, `The server refused it (${response.status})`, problems);
  }
  throw new ApiError(response.status, detail ?? `Request failed (${response.status})`);
}

const id = (value: string) => encodeURIComponent(value);

export const getQueue = () => request<ReviewQueue>("/reviews/queue");
export const getDecision = (decisionId: string) => request<ReviewDetail>(`/decisions/${id(decisionId)}`);
export const getTransaction = (txnId: string) => request<TransactionView>(`/transactions/${id(txnId)}`);
export const postReview = (decisionId: string, review: ReviewIn) =>
  request<ReviewOutcome>(`/decisions/${id(decisionId)}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(review),
  });
export const receiptFileUrl = (receiptId: string) => `${API_BASE}/receipts/${id(receiptId)}/file`;
