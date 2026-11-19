import { render, screen } from "@testing-library/react";
import { detail, mockApi } from "../test/data";
import { DecisionPage } from "./DecisionPage";

function show(name: string) {
  const d = detail(name);
  mockApi({ [`GET /api/decisions/${d.run.decision_id}`]: () => ({ body: d }) });
  render(<DecisionPage decisionId={d.run.decision_id} />);
  return d;
}

test("shows the transaction, the flags with their rule text, and the review form", async () => {
  const d = show("guardrails_unsure");
  const txn = d.snapshot.payload.transaction;
  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(txn.merchant_norm);
  expect(screen.getByText("Needs a person")).toBeInTheDocument();
  expect(screen.getByText(/OSU-GEN-06a · Title of OSU-GEN-06/)).toBeInTheDocument();
  expect(screen.getByText(/Text of OSU-GEN-06\./)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save review" })).toBeInTheDocument();
});

test("shows the receipt file and its reading", async () => {
  const d = show("lodging_stay_2");
  const receipt = d.snapshot.payload.receipt!;
  const frame = await screen.findByTitle("Receipt file");
  expect(frame).toHaveAttribute("src", `/api/receipts/${receipt.receipt_id}/file`);
  expect(screen.getByText(receipt.match_status)).toBeInTheDocument();
});

test("a rerun shows the earlier run and its review", async () => {
  show("lodging_stay_2");
  expect(await screen.findByText("Runs of this transaction")).toBeInTheDocument();
  expect(screen.getByText(/on an earlier run/)).toBeInTheDocument();
  expect(screen.getByText("This rerun disagrees with an earlier review")).toBeInTheDocument();
});

test("a run the agent is still working on can't be reviewed yet", async () => {
  show("agent_working");
  expect(await screen.findByText("This run can be reviewed once the agent has finished.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save review" })).not.toBeInTheDocument();
});

test("an unknown run shows the server's error", async () => {
  mockApi({ "GET /api/decisions/nope": () => ({ status: 404, body: { detail: "unknown decision_id" } }) });
  render(<DecisionPage decisionId="nope" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("unknown decision_id");
});
