// The report a scan returns (scanner.py and payments.py). Only the fields the page uses are listed.

export type Tone = "red" | "amber" | "green" | "info";
export type Severity = "critical" | "high" | "medium" | "low";

export interface Signal { tone: Tone; text: string }

export interface Category {
  key: string; name: string; score: number; grade: string;
  status: "good" | "warn" | "bad" | string; notes: string[]; issues: number;
}

export interface Finding { severity: Severity; title: string; location: string; fix: string; category: string }

export interface ListEntry { name: string; status: "listed" | "clear" | "skipped" | "error" | string; detail: string }

export interface PageFacts {
  url: string; redirected_to?: string | null; brands_named: string[];
  credential_form: "password" | "card" | null; form_built_by_script?: boolean; rendered: boolean;
}

export interface Impersonation {
  level: "official" | "clear" | "suspicious" | "likely" | "reported";
  verdict: string; summary: string; registrable: string; signals: Signal[];
  facts: { registered: string | null; registrar: string | null; first_certificate: string | null;
           certificate_source: string | null; page: PageFacts | null };
  lists: ListEntry[];
}

export interface Payment {
  level: "clear" | "caution" | "danger" | string; kind: "upi" | "provider" | "page" | string;
  verdict: string; summary: string; signals: Signal[]; facts: [string, string][];
}

export interface Criterion { text: string; passed: boolean; problem: string }

export interface Report {
  kind?: "upi";
  domain: string;
  resolves?: boolean;
  duration_ms?: number;
  risk: { score: number | null; label: "Low" | "Medium" | "High" | string } | null;
  // A UPI report has only kind, domain, risk and payment; website reports have the rest.
  categories?: Category[];
  findings?: Finding[];
  impersonation?: Impersonation | null;
  payment?: Payment | null;
  visit?: { allowed: boolean; url: string | null; criteria: Criterion[] } | null;
}

export interface Account { email: string; has_password: boolean; settings: Settings }

export interface Settings { theme: "system" | "light" | "dark"; same_tab: boolean }

export interface HistoryItem { target: string; risk_score: number | null; risk_label: string | null; verdict: string; scanned_at: number }

export type StepStatus = "ok" | "warn" | "bad" | "done" | "skipped";
export type ScanEvent =
  | { type: "step"; step: string; status: StepStatus }
  | { type: "done"; report: Report }
  | { type: "error"; message: string; code: number };
