"""Warning signs in payment requests: UPI links, payment pages on known providers, and pages that
collect card details or a UPI PIN.

UPI links are read, never fetched: everything needed is in the link itself. Artemis can't see who
owns a UPI ID, so the checks look for the tricks scams rely on, and remind people to check the
registered name their UPI app shows before paying.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

from clone import PageFeatures, claimed_brands
from impersonation import age_text, official_brand, registrable_domain

# Brands (from brands.py) whose domains host payment links and checkout pages for other businesses.
PAYMENT_PROVIDERS = {"PayPal", "Paytm", "PhonePe", "Razorpay", "PayU", "Cashfree", "Instamojo", "CCAvenue",
                     "BillDesk", "Stripe"}
UPI_ID = re.compile(r"^[a-zA-Z0-9._-]{2,256}@[a-zA-Z][a-zA-Z0-9]{1,63}$")
# Handles whose app is well known. Others exist (banks have their own); an unlisted handle isn't a warning.
UPI_APPS = {
    "ybl": "PhonePe", "ibl": "PhonePe", "axl": "PhonePe",
    "okaxis": "Google Pay", "okhdfcbank": "Google Pay", "okicici": "Google Pay", "oksbi": "Google Pay",
    "paytm": "Paytm", "ptyes": "Paytm", "ptaxis": "Paytm", "pthdfc": "Paytm", "ptsbi": "Paytm",
    "apl": "Amazon Pay", "yapl": "Amazon Pay",
    "upi": "BHIM",
}
# Words scams use to make paying look like receiving, or to borrow authority. They're chosen to be rare
# in genuine payee names ("Gift Store" or "Food Court" would be real shops).
MONEY_BAIT = re.compile(r"\b(refund|cash ?back|reward|prize|lottery|lucky draw|winner|won|claim|jackpot)\b",
                        re.IGNORECASE)
AUTHORITY = re.compile(r"\b(rbi|reserve bank|police|cyber ?cell|cyber ?crime|customs|income ?tax|cbi|trai|sebi|"
                       r"government|govt)\b", re.IGNORECASE)
PRETEXT = re.compile(r"\b(kyc|verify|verification|unblock|blocked|suspended|customer ?care|help ?desk)\b",
                     re.IGNORECASE)
NEW_SITE_DAYS = 90
TONE_ORDER = {"red": 0, "amber": 1, "green": 2, "info": 3}


def is_upi(raw: str) -> bool:
    """A UPI link (upi://pay?...) or a bare UPI ID (name@bank)."""
    text = raw.strip()
    return text.lower().startswith("upi:") or bool(UPI_ID.match(text))


def verdict(kind: str, signals: list[dict], facts: list[list[str]], clear_summary: str) -> dict:
    signals.sort(key=lambda s: TONE_ORDER[s["tone"]])
    tones = {s["tone"] for s in signals}
    level = "danger" if "red" in tones else "caution" if "amber" in tones else "clear"
    warnings = [s["text"] for s in signals if s["tone"] in ("red", "amber")]
    return {
        "kind": kind,
        "level": level,
        "verdict": {"danger": "Likely payment scam", "caution": "Check before paying",
                    "clear": "No payment warning signs"}[level],
        "summary": warnings[0] if warnings else clear_summary,
        "signals": signals,
        "facts": facts,
    }


def wording_signals(text: str, where: str, bait_tone: str = "red") -> list[dict]:
    """Bait, authority and pretext words in a payee name, payment note or page title."""
    signals = []
    if match := MONEY_BAIT.search(text):
        signals.append({"tone": bait_tone, "text": f"{where} says “{match.group(0)}”. Paying never brings you money: "
                                               "a refund, prize or cashback never needs you to pay or enter your UPI PIN."})
    if match := AUTHORITY.search(text):
        signals.append({"tone": "amber", "text": f"{where} uses the name “{match.group(0)}”. The RBI, police, courts "
                                                 "and tax officials don't ask people to pay by payment link. Check with them directly."})
    if match := PRETEXT.search(text):
        signals.append({"tone": "amber", "text": f"{where} mentions “{match.group(0)}”. Banks and support teams "
                                                 "never ask for a payment to update KYC, verify or unblock an account."})
    return signals


# ---------- UPI links ----------

def parse_upi(raw: str) -> tuple[str, dict[str, str]]:
    """(action, parameters) of a UPI link; a bare UPI ID counts as a payment to it."""
    text = raw.strip()
    if UPI_ID.match(text):
        return "pay", {"pa": text}
    parts = urlsplit(text)
    action = (parts.netloc or parts.path.strip("/")).lower()
    params = {key.lower(): values[0].strip() for key, values in parse_qs(parts.query).items() if values}
    return action, params


def check_upi(raw: str) -> dict:
    """Payment check for a UPI link or ID. Raises ValueError if it has no valid UPI ID."""
    action, params = parse_upi(raw)
    upi_id = params.get("pa", "")
    if not UPI_ID.match(upi_id):
        raise ValueError("This UPI link has no valid UPI ID (the pa= part).")
    local, handle = upi_id.rsplit("@", 1)
    name, note = params.get("pn", "")[:100], params.get("tn", "")[:200]
    signals: list[dict] = []
    facts = [["UPI ID", upi_id], ["Name in the link", name or "Not given"]]

    if action != "pay":
        signals.append({"tone": "amber", "text": f"This is a UPI “{action[:20]}” link, not an ordinary payment. "
                                                 "Read carefully what your UPI app asks you to approve."})
    bait_found = False
    for text, where in ((note, "The payment note"), (name, "The payee name")):
        found = wording_signals(text, where)
        bait_found = bait_found or any(s["tone"] == "red" for s in found)
        signals += [s for s in found if s["text"] not in {x["text"] for x in signals}]
    readable_id = re.sub(r"[._-]+", " ", local)
    brands = [b for b in claimed_brands(f"{name} {readable_id}") if b not in ("NPCI / BHIM UPI",)]
    if brands:
        signals.append({"tone": "amber", "text": f"The payee name or UPI ID uses the name {brands[0]}. Before paying, "
                                                 f"check your UPI app shows {brands[0]}'s registered name, not a person's."})

    amount = params.get("am")
    if amount:
        try:
            value = float(amount)
            if not math.isfinite(value) or value <= 0:
                raise ValueError
            currency = params.get("cu", "INR").upper()
            facts.append(["Amount", f"₹{value:,.2f}" if currency == "INR" else f"{value:,.2f} {currency[:3]}"])
        except ValueError:
            signals.append({"tone": "amber", "text": "The amount in the link isn't a valid number."})
    else:
        facts.append(["Amount", "Not set: you type it in"])
    if note:
        facts.append(["Note", note])
    app = UPI_APPS.get(handle.lower())
    facts.append(["UPI app", f"{app} (@{handle})" if app else f"@{handle}"])
    if params.get("mc") and params["mc"] != "0000":
        signals.append({"tone": "info", "text": "Marked as a merchant payment. Whoever made the link chooses this, "
                                                "so it doesn't prove the payee is a registered business."})
    signals.append({"tone": "info", "text": "Before you pay, your UPI app shows the name registered to this UPI ID. "
                                            "Pay only if it's who you expect."})
    if not bait_found:
        signals.append({"tone": "info", "text": "You never need to enter your UPI PIN to receive money."})
    return verdict("upi", signals, facts, "Nothing in this link matches common UPI scams.")


def upi_report(raw: str) -> dict:
    """A full /api/scan response for a UPI link or ID (no network: the link holds everything)."""
    payment = check_upi(raw)
    label = {"danger": "High", "caution": "Medium", "clear": "Low"}[payment["level"]]
    return {
        "kind": "upi",
        "domain": payment["facts"][0][1],   # the UPI ID
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_ms": 0,
        "risk": {"score": None, "label": label},
        "payment": payment,
    }


# ---------- payment pages ----------

def provider_of(host: str | None) -> str | None:
    brand = official_brand(registrable_domain(host)) if host else None
    return brand if brand in PAYMENT_PROVIDERS else None


def check_payment_page(host: str, features: PageFeatures | None, records: dict, link: str | None) -> dict | None:
    """Payment warning signs for a scanned page, or None when the page has nothing to do with payments."""
    site = registrable_domain(host)
    brand = official_brand(site)
    provider = brand if brand in PAYMENT_PROVIDERS else None
    forms = features.forms if features else []

    if provider:
        if not link:
            return None   # the provider's own homepage, not a payment page
        return provider_page(provider, site, features, records)
    if brand:
        return None       # a bank's or brand's own site: its payment forms are its own
    card_forms = [f for f in forms if f.get("card")]
    asks_pin = any(f.get("pin") for f in forms)
    if not card_forms and not asks_pin:
        return None

    signals: list[dict] = []
    page_url = features.url
    if asks_pin:
        signals.append({"tone": "red", "text": "Asks for a UPI PIN or ATM PIN. No genuine website needs these: "
                                               "you only ever enter your UPI PIN inside your UPI app."})
    own = [f for f in card_forms if not provider_of(f.get("frame"))]
    hosted = [provider_of(f.get("frame")) for f in card_forms if provider_of(f.get("frame"))]
    if hosted and not own:
        signals.append({"tone": "green", "text": f"Card details are typed into {hosted[0]}'s secure frame, not this site's page"})
    if own:
        before = len(signals)
        if page_url.startswith("http://"):
            signals.append({"tone": "red", "text": "Asks for card details without HTTPS, so they're sent unencrypted"})
        registered = (records.get("registration") or {}).get("registered")
        if registered:
            days = (datetime.now(timezone.utc) - registered).days
            if days < NEW_SITE_DAYS:
                signals.append({"tone": "red", "text": f"Asks for card details on a site registered only {age_text(days)}"})
        for form in own:
            action = (form.get("action") or "").strip()
            target = urlsplit(urljoin(page_url, action)).hostname if action.lower().startswith(("http", "/")) else None
            if target and registrable_domain(target) != site and not provider_of(target):
                signals.append({"tone": "red", "text": f"Sends card details to {target}, which isn't this site "
                                                       "or a known payment provider"})
                break
        if any(f.get("otp") for f in forms):
            signals.append({"tone": "amber", "text": "Asks for card details and a one-time password (OTP) together. "
                                                     "Banks ask for the OTP on their own page, not the shop's."})
        if len(signals) == before:
            signals.append({"tone": "info", "text": "Takes card details in its own page rather than a payment "
                                                    "provider's. Many real shops do this; on its own it isn't a warning."})
    asks = [label for label, present in (("Card details", bool(card_forms)), ("UPI or ATM PIN", asks_pin),
                                         ("One-time password", any(f.get("otp") for f in forms))) if present]
    facts = [["Asks for", ", ".join(asks)],
             ["Card fields provided by", (hosted[0] if hosted and not own else "This site") if card_forms else "None"]]
    return verdict("page", signals, facts, "Nothing on this page matches common payment scams.")


def provider_page(provider: str, site: str, features: PageFeatures | None, records: dict) -> dict:
    """A page on a payment provider's real domain: the domain is fine, the question is who gets paid."""
    signals = [
        {"tone": "green", "text": f"Real {provider} address ({site})"},
        {"tone": "info", "text": f"Businesses and individuals can create payment pages on {provider}, so a real "
                                 f"{provider} address doesn't tell you who gets the money. Check the name on the page."},
    ]
    title = ""
    if features:
        title = (features.meta.get("og:title") or features.meta.get("og:site_name") or features.title).strip()[:200]
    if title:
        named = [b for b in claimed_brands(title) if b not in PAYMENT_PROVIDERS]
        if named:
            signals.append({"tone": "amber", "text": f"The page title names {named[0]}. Check this payment really goes "
                                                     f"to {named[0]}: scammers put well-known names on payment pages."})
        # A title is weaker evidence than a UPI note, so bait words there are a caution, not a verdict.
        signals += wording_signals(title, "The page title", bait_tone="amber")
    if any(entry["status"] == "listed" for entry in records.get("lists", [])):
        signals.append({"tone": "red", "text": "This payment link is on a phishing or malware list"})
    facts = [["Provider", provider], ["Page title", title or "None"]]
    return verdict("provider", signals, facts, f"A real {provider} payment page with no warning signs in its title.")
