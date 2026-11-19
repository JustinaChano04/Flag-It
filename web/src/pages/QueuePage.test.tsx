import { render, screen } from "@testing-library/react";
import { detail, mockApi, run } from "../test/data";
import { QueuePage } from "./QueuePage";

test("lists each waiting run with its merchant, amount and reason", async () => {
  const waiting = run("agent_failed");
  const txn = detail("agent_failed").snapshot.payload.transaction;
  const summary = {
    decision_id: waiting.decision_id, merchant: txn.merchant_norm, amount: txn.amount, transaction_date: txn.transaction_date,
  };
  // Only the queue is mocked: the screen must not ask for each transaction.
  mockApi({
    "GET /api/reviews/queue": () => ({ body: { contract_version: "1.1.0", items: [waiting], summaries: [summary] } }),
  });
  render(<QueuePage />);
  const link = await screen.findByRole("link", { name: txn.merchant_norm });
  expect(link).toHaveAttribute("href", `#/decisions/${waiting.decision_id}`);
  expect(screen.getByText(`$${txn.amount}`)).toBeInTheDocument();
  expect(screen.getByText("The agent failed to answer")).toBeInTheDocument();
});

test("a run without a summary still shows, with an unknown merchant", async () => {
  const waiting = run("agent_failed");
  mockApi({ "GET /api/reviews/queue": () => ({ body: { contract_version: "1.1.0", items: [waiting], summaries: [] } }) });
  render(<QueuePage />);
  const link = await screen.findByRole("link", { name: "(unknown)" });
  expect(link).toHaveAttribute("href", `#/decisions/${waiting.decision_id}`);
});

test("says so when nothing is waiting", async () => {
  mockApi({ "GET /api/reviews/queue": () => ({ body: { items: [] } }) });
  render(<QueuePage />);
  expect(await screen.findByText("Nothing is waiting for review.")).toBeInTheDocument();
});

test("shows an error when the queue can't be loaded", async () => {
  mockApi({ "GET /api/reviews/queue": () => ({ status: 500, body: { detail: "database down" } }) });
  render(<QueuePage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("database down");
});
