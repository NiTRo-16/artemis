"""Measure how well Artemis separates phishing from genuine sites, from evaluation/data/results.jsonl.

    python evaluation/report.py           print the summary and write evaluation/data/report.md

Two views of every scan:
  with lists     Artemis as users get it (OpenPhish, and Safe Browsing and URLhaus when keys are set)
  without lists  the verdict Artemis would give if no blocklist knew the site. The phishing links come
                 from OpenPhish, which Artemis also checks, so this is the honest measure of its own
                 checks. It is computed from the same scan: blocklist entries add no points, they only
                 change the verdict, so removing them gives exactly the verdict Artemis would reach.

Two questions for each view:
  flagged        did Artemis say the site imitates a brand, is listed, or is a payment scam?
  no safe link   did Artemis withhold the direct link (any safety criterion failed)?
"""
from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
RESULTS = DATA / "results.jsonl"
LIST_SIGNAL = "This payment link is on a phishing or malware list"
FLAG_LEVELS = {"suspicious", "likely", "reported"}


def level_without_lists(r: dict) -> str:
    if r["imp_level"] == "official":
        return "official"
    points = r["imp_points"]
    return "likely" if points >= 60 else "suspicious" if points >= 25 else "clear"


def payment_without_lists(r: dict) -> str | None:
    signals = [s for s in (r.get("payment_signals") or []) if s["text"] != LIST_SIGNAL]
    if r.get("payment_level") is None:
        return None
    tones = {s["tone"] for s in signals}
    return "danger" if "red" in tones else "caution" if "amber" in tones else "clear"


def verdicts(r: dict, with_lists: bool) -> tuple[bool, bool]:
    """(flagged, no safe link) for one scan."""
    if with_lists:
        flagged = r["imp_level"] in FLAG_LEVELS or r.get("payment_level") == "danger"
        return flagged, not r["allowed"]
    level, pay = level_without_lists(r), payment_without_lists(r)
    flagged = level in FLAG_LEVELS or pay == "danger"
    failed = set(r["failed_criteria"]) - {"Not on any phishing or malware list"}
    if level in ("official", "clear"):
        failed.discard("No signs of impersonating a brand")
    if pay != "danger":
        failed.discard("No signs of a payment scam")
    return flagged, bool(failed)


def wilson(k: int, n: int) -> tuple[float, float]:
    """95% confidence interval for a proportion (Wilson score)."""
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> str:
    if n == 0:
        return "no data"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.1f}% (95% CI {100 * lo:.1f} to {100 * hi:.1f}%)"


def shape(text: str) -> str:
    """Signal text with the specifics removed, so the same kind of signal is counted together."""
    text = re.sub(r"“[^”]*”", "“…”", text)
    text = re.sub(r"\([^)]*\)", "(…)", text)
    text = re.sub(r"\d+", "N", text)
    return re.sub(r"\b(?:[A-Z][\w&.-]*\s?){1,3}(?=['’]s\b)", "BRAND", text)


def main() -> None:
    if not RESULTS.exists():
        raise SystemExit("No results yet. Run evaluation/run.py first.")
    rows = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    errors = [r for r in rows if "error" in r]
    ok = [r for r in rows if "error" not in r]
    lines = ["# Artemis evaluation", ""]
    phish = [r for r in ok if r["label"] == "phishing"]
    good = [r for r in ok if r["label"] == "genuine"]
    lines += [f"Scans: {len(rows)} ({len(phish)} phishing, {len(good)} genuine, {len(errors)} errors).",
              f"Phishing sites still online when scanned: {sum(r['online'] for r in phish)} of {len(phish)}.", ""]

    for with_lists in (True, False):
        name = "With blocklists" if with_lists else "Without blocklists (Artemis's own checks)"
        lines += [f"## {name}", ""]
        for subset_name, subset in (("all", ok), ("online only", [r for r in ok if r["online"]])):
            p = [r for r in subset if r["label"] == "phishing"]
            g = [r for r in subset if r["label"] == "genuine"]
            tp = sum(verdicts(r, with_lists)[0] for r in p)
            fp = sum(verdicts(r, with_lists)[0] for r in g)
            p_warn = sum(verdicts(r, with_lists)[1] for r in p)
            g_warn = sum(verdicts(r, with_lists)[1] for r in g)
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / len(p) if p else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            lines += [f"### {subset_name}", "",
                      f"- Phishing flagged: {rate(tp, len(p))}",
                      f"- Genuine sites wrongly flagged: {rate(fp, len(g))}",
                      f"- Phishing given no safe link: {rate(p_warn, len(p))}",
                      f"- Genuine sites given no safe link: {rate(g_warn, len(g))}",
                      f"- Precision {precision:.3f}, recall {recall:.3f}, F1 {f1:.3f} "
                      f"(precision depends on the dataset's mix of phishing and genuine sites)", ""]

    for label, subset in (("phishing", phish), ("genuine", good)):
        counts = Counter(shape(s["text"]) for r in subset for s in r["signals"] if s["tone"] in ("red", "amber"))
        lines += [f"## Most common warning signals on {label} sites", ""]
        lines += [f"- {n} x {text}" for text, n in counts.most_common(12)] or ["- none"]
        lines.append("")

    missed = [r for r in phish if not verdicts(r, False)[0]]
    false_alarms = [r for r in good if verdicts(r, True)[0]]
    lines += ["## Phishing missed by Artemis's own checks (sample)", ""]
    lines += [f"- {r['url'][:100]} (online: {r['online']}, points {r['imp_points']})" for r in missed[:20]] or ["- none"]
    lines += ["", "## Genuine sites wrongly flagged (all)", ""]
    lines += [f"- {r['url']}: " + "; ".join(s["text"] for s in r["signals"] if s["tone"] in ("red", "amber"))[:200]
              for r in false_alarms] or ["- none"]
    times = [r["seconds"] for r in ok]
    if times:
        times.sort()
        lines += ["", "## Scan time", "",
                  f"Median {statistics.median(times):.1f} s, 90th percentile {times[int(0.9 * (len(times) - 1))]:.1f} s, "
                  f"slowest {times[-1]:.1f} s."]
    if errors:
        lines += ["", "## Errors", ""] + [f"- {r['url'][:80]}: {r['error']}" for r in errors[:20]]

    text = "\n".join(lines) + "\n"
    (DATA / "report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
