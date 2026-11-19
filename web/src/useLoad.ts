import { useEffect, useState } from "react";

export type Load<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: T };

/** Runs `load` when `key` changes, and ignores an answer that arrives after a newer request. */
export function useLoad<T>(load: () => Promise<T>, key: string): Load<T> {
  const [result, setResult] = useState<Load<T>>({ state: "loading" });
  useEffect(() => {
    let current = true;
    setResult({ state: "loading" });
    load().then(
      (data) => {
        if (current) setResult({ state: "ready", data });
      },
      (error: unknown) => {
        if (current) setResult({ state: "error", message: error instanceof Error ? error.message : String(error) });
      },
    );
    return () => {
      current = false;
    };
    // `load` is a new function on every render; `key` says when the request really changes.
  }, [key]);
  return result;
}
