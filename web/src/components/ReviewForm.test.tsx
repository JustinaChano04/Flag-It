import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { loadReviewer } from "../reviewer";
import { detail, mockApi } from "../test/data";
import { parseRuleIds, ReviewForm } from "./ReviewForm";

const d = detail("guardrails_unsure");
const url = `POST /api/decisions/${d.run.decision_id}/review`;

test("sends the final call, each answered flag, missed rules and the reason", async () => {
  const fetchMock = mockApi({ [url]: () => ({ status: 201, body: {} }) });
  render(<ReviewForm decisionId={d.run.decision_id} flags={d.flags} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Your name"), "Ana");
  await user.click(screen.getByLabelText("Agree"));
  await user.type(screen.getByLabelText("Note"), "No purpose given");
  await user.type(screen.getByLabelText(/Rules the system missed/), "osu-lim-01, OSU-LIM-01");
  await user.type(screen.getByLabelText("Reason"), "Student chapter dues.");
  await user.click(screen.getByLabelText("Flag"));
  await user.click(screen.getByRole("button", { name: "Save review" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Review saved");
  const sent = JSON.parse(fetchMock.mock.calls[0][1]!.body as string);
  expect(sent).toEqual({
    reviewer: "Ana",
    final: "flag",
    per_flag: [{ flag_id: d.flags[0].flag_id, agree: true, note: "No purpose given" }],
    missed_rule_ids: ["OSU-LIM-01"],
    reason: "Student chapter dues.",
  });
  expect(loadReviewer()).toBe("Ana");
});

test("can't be sent without a final call", async () => {
  render(<ReviewForm decisionId={d.run.decision_id} flags={d.flags} />);
  await userEvent.setup().type(screen.getByLabelText("Your name"), "Ana");
  expect(screen.getByRole("button", { name: "Save review" })).toBeDisabled();
  expect(screen.getByText("1 flag(s) not answered yet.")).toBeInTheDocument();
});

test("shows each problem the server reports", async () => {
  mockApi({
    [url]: () => ({
      status: 422,
      body: { detail: [{ loc: ["body", "missed_rule_ids", "0"], msg: "OSU-XYZ-99 is not an active rule" }] },
    }),
  });
  render(<ReviewForm decisionId={d.run.decision_id} flags={[]} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Your name"), "Ana");
  await user.type(screen.getByLabelText(/Rules the system missed/), "OSU-XYZ-99");
  await user.click(screen.getByLabelText("Approve"));
  await user.click(screen.getByRole("button", { name: "Save review" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("missed_rule_ids.0: OSU-XYZ-99 is not an active rule");
});

test("rule IDs are split on commas and spaces, upper-cased and deduplicated", () => {
  expect(parseRuleIds(" osu-lim-01,OSU-TRV-13  osu-lim-01 ")).toEqual(["OSU-LIM-01", "OSU-TRV-13"]);
  expect(parseRuleIds("")).toEqual([]);
});
