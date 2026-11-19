// The reviewer's name. There is no login in v1, so the name is typed once and remembered in this
// browser. Storage can be blocked (private windows), so every access is guarded.
const KEY = "flag-it.reviewer";

export function loadReviewer(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveReviewer(name: string): void {
  try {
    localStorage.setItem(KEY, name.trim());
  } catch {
    // not remembered; the form still works
  }
}
