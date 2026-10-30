"""Domain watch's fast name check: does a new certificate's name copy a known brand?

The logs carry hundreds of names a second and brand_lookalike takes over a millisecond each, so a compiled
filter comes first and only the few names that pass reach it. Its wording and rules stay the one source.
Accepted limit: typos beyond one edit are missed here, though a normal scan still catches them.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass

from brands import BRANDS
from impersonation import RISKY_TLDS, _extract, brand_lookalike, decode_label, official_brand, registrable_domain, skeleton

SHORT = 6   # keywords shorter than this appear in many innocent names, so they need a second clue
# Long enough, but ordinary words or easily found inside them (pianoledger, energy-outlook, virtualcloud).
COMMON_WORDS = {"ledger", "outlook", "blockchain", "kraken", "icloud", "discord", "apple", "adobe", "slack", "chase"}
# Short, but appear in almost nothing else, and these are the names Artemis most needs to catch.
DISTINCTIVE = {"hdfc", "icici", "paytm", "npci"}
REAL_WORDS = {"finance"}   # one letter from a brand, but an everyday word
CLUES = {"login", "signin", "kyc", "verify", "verification", "secure", "bank", "banking", "netbanking", "pay",
         "payment", "update", "reward", "rewards", "refund", "account", "otp", "upi", "card", "support"}
_CLUE_SKELETONS = {skeleton(word) for word in CLUES}
# Scanned first: the daily cap would otherwise go on far more common global names.
INDIAN_BRANDS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Paytm", "PhonePe", "NPCI / BHIM UPI",
                 "Razorpay", "PayU", "Cashfree", "Instamojo", "CCAvenue", "BillDesk", "Income Tax India", "Flipkart"]


def _one_typo(word: str) -> set[str]:
    letters = string.ascii_lowercase + string.digits
    out = set()
    for i in range(len(word) + 1):
        out.update(word[:i] + ch + word[i:] for ch in letters)     # one extra letter
        if i < len(word):
            out.add(word[:i] + word[i + 1:])                       # one missing
            out.update(word[:i] + ch + word[i + 1:] for ch in letters)   # one wrong
        if i < len(word) - 1:
            out.add(word[:i] + word[i + 1] + word[i] + word[i + 2:])     # two swapped
    out.discard(word)
    return {skeleton(w) for w in out}


_keywords = {skeleton(kw) for _, kws, _ in BRANDS for kw in kws}
_loose = {skeleton(w) for w in COMMON_WORDS} | {k for k in _keywords if len(k) < SHORT} - {skeleton(w) for w in DISTINCTIVE}
_firm = sorted(_keywords - _loose, key=len, reverse=True)
_FIRM_RX = re.compile("|".join(map(re.escape, _firm)))
_FIRM_TYPOS = {t for k in _firm if len(k) >= 5 for t in _one_typo(k)} - _keywords - {skeleton(w) for w in REAL_WORDS}
_LOOSE_TYPOS = {t for k in _loose if len(k) >= 5 for t in _one_typo(k)} - _keywords
_NON_LETTERS = re.compile(r"[^a-z]+")
# A brand's real address used as the start of someone else's: support.zoom.us.tokovpn.com
_REAL_ADDRESS_RX = re.compile(r"(?:^|\.)(?:" + "|".join(sorted((re.escape(d) for _, kws, ds in BRANDS if kws for d in ds), key=len, reverse=True)) + r")\.")


@dataclass
class Match:
    host: str
    registrable: str
    brand: str
    reason: str


def _loose_name_counts(text: str, labels: list[str], host: str) -> bool:
    """A loose keyword counts only as a whole word in the part its owner registered, alongside a clue."""
    tokens = set(_NON_LETTERS.split(text)) - {""}
    if not (tokens & _loose or any(label in _LOOSE_TYPOS for label in labels)):
        return False
    if not (tokens & _CLUE_SKELETONS or labels[-1] in RISKY_TLDS):
        return False
    own = _extract(host).domain.translate(_ASCII_SKELETON).replace("rn", "m").replace("vv", "w")
    return bool(set(_NON_LETTERS.split(own)) & _loose) or own in _LOOSE_TYPOS


def _passes_filter(text: str, host: str) -> bool:
    """text is the skeleton of the whole name."""
    labels = text.split(".")
    if _FIRM_RX.search(text) or any(label in _FIRM_TYPOS for label in labels) or _REAL_ADDRESS_RX.search(host):
        return True
    return _loose_name_counts(text, labels, host)


def match(name: str) -> Match | None:
    """The brand this certificate name copies, or None."""
    host = name.lower().removeprefix("*.").rstrip(".")
    if "." not in host or len(host) > 253:
        return None
    # skeleton() is the slow part of the filter. Plain ASCII needs only its letter swaps.
    text = host.translate(_ASCII_SKELETON).replace("rn", "m").replace("vv", "w")
    if "xn--" in host:
        text = ".".join(skeleton(decode_label(label)) for label in host.split("."))
    if not _passes_filter(text, host):
        return None
    parts = _extract(host)
    if not parts.suffix or not parts.domain:
        return None
    registrable = registrable_domain(host)
    if official_brand(registrable):
        return None
    hit = brand_lookalike(parts.domain, parts.subdomain)
    if hit is None:
        return None
    return Match(host, registrable, hit[2], hit[1])


_ASCII_SKELETON = str.maketrans({ch: skeleton(ch) for ch in string.ascii_lowercase + string.digits + "-."})
