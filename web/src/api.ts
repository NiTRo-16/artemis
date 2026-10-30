// Calls to the Artemis backend. Every function throws an Error whose message can be shown to the user.
import type { Account, HistoryItem, Report, Settings } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: options.method ?? "GET",
      headers: options.body !== undefined ? { "Content-Type": "application/json" } : {},
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new ApiError("Couldn't reach Artemis. Check your connection and try again.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.";
    throw new ApiError(detail, res.status);
  }
  return data as T;
}

export type StartedScan = { id: string; status: "queued" | "done" } | { id: null; status: "done"; report: Report };

export const startScan = (target: string) => api<StartedScan>("/api/scans", { method: "POST", body: { target } });
export const getScan = (id: string) =>
  api<{ id: string; status: string; report?: Report; error?: string; code?: number }>(`/api/scans/${encodeURIComponent(id)}`);
export const shareScan = (id: string) => api<{ url: string }>(`/api/scans/${encodeURIComponent(id)}/share`, { method: "POST" });
export const getShared = (id: string) => api<Report>(`/api/shared/${encodeURIComponent(id)}`);

export type WatchSummary = {
  public: boolean;
  brands: { brand: string; matches: number; forms: number; listed: number; checked: number }[];
  logs: string[];
  last_read: number | null;
  last_gap: number | null;
  stopped: boolean;
  just_started: boolean;
};
export const getWatchSummary = () => api<WatchSummary>("/api/watch/summary");

export const me = () => api<{ account: Account | null; google_signin: boolean }>("/api/me");
export const signup = (email: string, password: string, name: string) => api("/api/signup", { method: "POST", body: { email, password, name } });
export const putName = (name: string) => api<{ name: string }>("/api/account/name", { method: "PUT", body: { name } });
export const login = (email: string, password: string) => api<Account>("/api/login", { method: "POST", body: { email, password } });
export const verifyEmail = (token: string, password: string) => api<Account>("/api/verify", { method: "POST", body: { token, password } });
export const forgotPassword = (email: string) => api("/api/password/forgot", { method: "POST", body: { email } });
export const resetPassword = (token: string, password: string) =>
  api<Account>("/api/password/reset", { method: "POST", body: { token, password } });
export const logout = () => api("/api/logout", { method: "POST" });
export const deleteAccount = (password: string) => api("/api/account/delete", { method: "POST", body: { password } });
export const putSettings = (settings: Settings) => api("/api/settings", { method: "PUT", body: settings });
export const getHistory = () => api<{ scans: HistoryItem[] }>("/api/history");
export const clearHistory = () => api("/api/history", { method: "DELETE" });
export const sendReport = (target: string, category: string, details: string) =>
  api("/api/report", { method: "POST", body: { target, category, details } });
