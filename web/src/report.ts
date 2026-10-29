// Reading a report: what made it risky, and whether it can be reported.
import type { Report, Tone } from "./types";

/** Everything that made the site high risk, strongest first, without repeats. */
export function riskFactors(report: Report): { text: string; tone: Tone }[] {
  const items: { text: string; tone: Tone }[] = [];
  const add = (text: string, tone: Tone) => {
    const plain = text.replaceAll("`", "");
    if (!items.some((i) => i.text === plain)) items.push({ text: plain, tone });
  };
  const imp = report.impersonation?.signals ?? [];
  const pay = report.payment?.signals ?? [];
  // A critical certificate finding already says what the "certificate" criterion would, in more detail.
  const findings = report.findings ?? [];
  const certFinding = findings.some((f) => f.severity === "critical" && f.category === "TLS / HTTPS");
  (report.visit?.criteria ?? [])
    .filter((c) => !c.passed && !(certFinding && c.text === "Certificate is valid and trusted"))
    .forEach((c) => add(c.problem, "red"));
  pay.filter((s) => s.tone === "red").forEach((s) => add(s.text, "red"));
  imp.filter((s) => s.tone === "red").forEach((s) => add(s.text, "red"));
  findings.filter((f) => f.severity === "critical" || f.severity === "high").forEach((f) => add(f.title, "red"));
  pay.filter((s) => s.tone === "amber").forEach((s) => add(s.text, "amber"));
  imp.filter((s) => s.tone === "amber").forEach((s) => add(s.text, "amber"));
  return items;
}

/** Sites showing signs of phishing, malware or a payment scam can be reported. */
export function reportable(report: Report): boolean {
  return ["suspicious", "likely", "reported"].includes(report.impersonation?.level ?? "")
    || (!!report.payment && report.payment.level !== "clear");
}

/** The address to report: the UPI ID, or the page that was checked. */
export function reportTarget(report: Report): string {
  return report.kind === "upi" ? report.domain : report.visit?.url || report.domain;
}

export function riskTone(report: Report): "low" | "medium" | "high" | "none" {
  const label = report.risk?.label?.toLowerCase();
  return label === "low" || label === "medium" || label === "high" ? label : "none";
}

/** A link's URL only if it's a web address, so a report can never produce a javascript: link. */
export function safeUrl(url: string | null | undefined): string | null {
  return url && /^https?:\/\//.test(url) ? url : null;
}
