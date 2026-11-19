// Two screens, chosen by the URL hash: #/ is the queue, #/decisions/<id> is one run.
import { useEffect, useState } from "react";

export type Route = { page: "queue" } | { page: "decision"; decisionId: string };

export function parseRoute(hash: string): Route {
  const match = /^#\/decisions\/([^/]+)$/.exec(hash);
  return match ? { page: "decision", decisionId: decodeURIComponent(match[1]) } : { page: "queue" };
}

export const decisionHref = (decisionId: string) => `#/decisions/${encodeURIComponent(decisionId)}`;

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
