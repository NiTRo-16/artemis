// The last few searches, kept in this browser only (never sent anywhere).
const KEY = "artemis.recent";
const MAX = 5;

export function loadRecent(): string[] {
  try {
    const list = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(list) ? list.filter((t): t is string => typeof t === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function saveRecent(list: string[]): void {
  try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX))); } catch { /* storage unavailable */ }
}

export function rememberSearch(target: string): void {
  saveRecent([target, ...loadRecent().filter((t) => t.toLowerCase() !== target.toLowerCase())]);
}

/** Recent searches matching what's typed (all of them when the box is empty). */
export function matchingRecent(typed: string): string[] {
  const q = typed.trim().toLowerCase();
  return loadRecent().filter((t) => !q || (t.toLowerCase().includes(q) && t.toLowerCase() !== q));
}
