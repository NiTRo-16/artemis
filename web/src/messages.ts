// The message check's result, and how it's shown.
import type { Report } from "./types";

export type Level = "clear" | "caution" | "danger";
export interface MessageMatch { start: number; end: number; script: string }
export interface MessageItem {
  kind: "link" | "upi" | "phone";
  value: string;
  payment?: { level: Level; verdict: string; summary: string };
}
export interface MessageResult {
  level: Level;
  verdict: string;
  summary: string;
  scripts: { id: string; title: string; explanation: string; strength: "strong" | "medium" }[];
  matches: MessageMatch[];
  items: MessageItem[];
}

const RANK: Record<Level, number> = { clear: 0, caution: 1, danger: 2 };

/** The message split into plain and marked parts, joining matches that overlap. */
export function highlight(text: string, matches: MessageMatch[]): { text: string; marked: boolean }[] {
  const parts: { text: string; marked: boolean }[] = [];
  let at = 0;
  const sorted = [...matches].sort((a, b) => a.start - b.start);
  for (let i = 0; i < sorted.length; i++) {
    const start = sorted[i].start;
    let end = sorted[i].end;
    while (i + 1 < sorted.length && sorted[i + 1].start <= end) end = Math.max(end, sorted[++i].end);
    if (start > at) parts.push({ text: text.slice(at, start), marked: false });
    parts.push({ text: text.slice(start, end), marked: true });
    at = end;
  }
  if (at < text.length || !parts.length) parts.push({ text: text.slice(at), marked: false });
  return parts;
}

/** What a scanned link means for the message. Goes by signs of a fake site: ordinary sites often get a
 *  Medium score just for missing security headers, which says nothing about whether a message is a scam. */
export function linkLevel(report: Report): Level {
  const imp = report.impersonation?.level;
  if (imp === "likely" || imp === "reported" || report.payment?.level === "danger") return "danger";
  if (imp === "suspicious" || report.payment?.level === "caution" || report.risk?.label === "High") return "caution";
  return "clear";
}

export function overallLevel(wording: Level, links: Level[]): Level {
  return [wording, ...links].reduce((worst, l) => (RANK[l] > RANK[worst] ? l : worst), "clear" as Level);
}
