// The result page and recent searches, rendered from reports shaped exactly like the backend's.
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { AccountProvider } from "./account";
import { ResultView } from "./pages/ResultPage";
import { loadRecent, matchingRecent, rememberSearch, saveRecent } from "./recent";
import { reportable, riskFactors, safeUrl } from "./report";
import type { Report } from "./types";

globalThis.fetch = (async () => new Response(JSON.stringify({ account: null, google_signin: false }))) as typeof fetch;
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.open = true; };
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.open = false; };
afterEach(cleanup);

const imp = (level: "official" | "clear" | "likely", signals: Report["impersonation"] extends infer I ? I extends { signals: infer S } ? S : never : never = []) => ({
  level, verdict: level === "likely" ? "Likely impersonation" : level === "official" ? "Official GitHub domain" : "No impersonation signs",
  summary: "", registrable: "example.org", signals,
  facts: { registered: "2016-10-23", registrar: "Registrar", first_certificate: null, certificate_source: null, page: null },
  lists: [{ name: "OpenPhish", status: "clear", detail: "Not among active phishing hosts" }],
});

const safe: Report = {
  domain: "example.org", resolves: true, duration_ms: 4100, risk: { score: 8, label: "Low" },
  categories: [{ key: "tls", name: "TLS / HTTPS", score: 100, grade: "A+", status: "good", notes: [], issues: 0 }],
  findings: [], impersonation: imp("clear"), payment: null,
  visit: { allowed: true, url: "https://example.org/", criteria: [{ text: "Homepage loads over HTTPS", passed: true, problem: "Site is offline" }] },
};

const risky: Report = {
  ...safe, domain: "paypa1-login.example", risk: { score: 82, label: "High" },
  findings: [{ severity: "critical", title: "Login form sends to `collect.example`", location: "/", fix: "Don't use it", category: "Page" }],
  impersonation: imp("likely", [{ tone: "red", text: "Spelled with lookalike characters to read as PayPal" }]),
  visit: { allowed: false, url: "https://paypa1-login.example/",
           criteria: [{ text: "No signs of impersonating a brand", passed: false, problem: "Impersonation check: Likely impersonation" }] },
};

// Exactly the fields payments.upi_report returns: no categories, findings, impersonation or visit.
const upi: Report = {
  kind: "upi", domain: "refund.desk@okaxis", risk: { score: null, label: "High" },
  payment: { level: "danger", kind: "upi", verdict: "Likely a payment scam", summary: "Paying never gets you a refund.",
             signals: [{ tone: "red", text: "The note asks for a refund payment" }], facts: [["Pays to", "refund.desk@okaxis"]] },
};

function show(report: Report, shareId: string | null = "abcdefghijklmnop") {
  return render(<MemoryRouter><AccountProvider><ResultView report={report} shareId={shareId} /></AccountProvider></MemoryRouter>);
}

describe("result page", () => {
  it("links straight to a safe site, in a new tab by default", () => {
    show(safe);
    const link = screen.getByRole("link", { name: "Continue to example.org" });
    expect(link.getAttribute("href")).toBe("https://example.org/");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.queryByRole("button", { name: /Report/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Share result/ })).toBeTruthy();
  });

  it("warns before a risky site and offers a report", () => {
    show(risky);
    expect(screen.queryByRole("link", { name: /Continue to/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Continue anyway" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Report site/ })).toBeTruthy();
    expect(screen.getAllByText("Impersonation check: Likely impersonation")).toHaveLength(2);   // reasons and "Safe to visit?"
    expect(screen.getAllByText("collect.example")[0].tagName).toBe("CODE");   // `backticks` become code
  });

  it("shows only the payment check for a UPI link, without a share button", () => {
    show(upi, null);
    expect(screen.getByText("Likely a payment scam", { selector: "h3" })).toBeTruthy();
    expect(screen.getByText("Unsafe").className).toContain("bad");
    expect(screen.getByRole("button", { name: /Report this UPI ID/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Share result/ })).toBeNull();
    expect(screen.queryByText("Security checks")).toBeNull();
  });
});

describe("report helpers", () => {
  it("lists risk factors without repeats, strongest first", () => {
    const items = riskFactors(risky);
    expect(items[0]).toEqual({ text: "Impersonation check: Likely impersonation", tone: "red" });
    expect(new Set(items.map((i) => i.text)).size).toBe(items.length);
  });
  it("knows what can be reported", () => {
    expect(reportable(safe)).toBe(false);
    expect(reportable(risky)).toBe(true);
    expect(reportable(upi)).toBe(true);
  });
  it("never produces a link that isn't a web address", () => {
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("https://example.org/")).toBe("https://example.org/");
  });
});

describe("recent searches", () => {
  it("keeps the last five, newest first, without case-insensitive repeats", () => {
    saveRecent([]);
    ["a.com", "b.com", "c.com", "d.com", "e.com", "f.com", "B.COM"].forEach(rememberSearch);
    expect(loadRecent()).toEqual(["B.COM", "f.com", "e.com", "d.com", "c.com"]);
    expect(matchingRecent("e.c")).toEqual(["e.com"]);
    expect(matchingRecent("")).toHaveLength(5);
  });
});
