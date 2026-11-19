import { decisionHref, parseRoute } from "./route";

test("the hash picks the screen", () => {
  expect(parseRoute("")).toEqual({ page: "queue" });
  expect(parseRoute("#/")).toEqual({ page: "queue" });
  expect(parseRoute("#/decisions/abc-123")).toEqual({ page: "decision", decisionId: "abc-123" });
  expect(parseRoute("#/decisions/abc/extra")).toEqual({ page: "queue" });
});

test("decision links round-trip", () => {
  expect(parseRoute(decisionHref("a b"))).toEqual({ page: "decision", decisionId: "a b" });
});
