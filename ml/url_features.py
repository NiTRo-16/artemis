"""Features of a web address's hostname, for the URL model.

Only the hostname is used, with any leading "www." removed. The scheme, "www.", path and query are left out
on purpose: in public training data, genuine addresses are almost all bare https://www. homepages, so a
model that saw them would learn "has a path = phishing" instead of anything about phishing itself.

Each feature has a plain-language description, used to explain a score to the user.
"""
from __future__ import annotations

import ipaddress
import math
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tldextract  # noqa: E402

from brands import BRANDS  # noqa: E402
from impersonation import RISKY_TLDS, lookalike_brand, official_brand, registrable_domain  # noqa: E402

# Public suffixes only (".app", ".co.in"), so a site on netlify.app gets ".app" as its ending and its own
# subdomain as text before the name; free hosting is a separate feature.
_public = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=False)

COMMON_TLDS = {"com", "org", "net", "edu", "gov", "in", "co.in", "uk", "co.uk", "de", "fr", "jp", "au", "ca",
               "io", "us", "nl", "it", "es", "ac.in", "gov.in", "bank.in", "sbi"}
# Services where anyone can publish a site on a subdomain; a page there isn't the service's own.
FREE_HOSTS = {"netlify.app", "vercel.app", "github.io", "pages.dev", "web.app", "firebaseapp.com",
              "repl.co", "replit.app", "glitch.me", "herokuapp.com", "onrender.com", "weebly.com",
              "wixsite.com", "blogspot.com", "000webhostapp.com", "webflow.io", "framer.app", "godaddysites.com",
              "square.site", "ngrok.io", "ngrok-free.app", "workers.dev", "azurewebsites.net", "web.core.windows.net",
              "storage.googleapis.com", "appspot.com", "wordpress.com", "sites.google.com", "myshopify.com",
              "gitbook.io", "notion.site", "carrd.co", "surge.sh", "fly.dev", "mystrikingly.com", "jimdosite.com"}
BAIT_WORDS = ("login", "logon", "signin", "sign-in", "secure", "verify", "verification", "account", "update",
              "support", "wallet", "kyc", "bank", "auth", "recovery", "unlock", "billing", "invoice", "refund",
              "bonus", "reward", "claim", "gift", "free", "confirm", "service", "helpdesk", "webmail", "office")
BRAND_WORDS = sorted({k for _, keys, _ in BRANDS for k in keys if len(k) >= 4})

# (name, what it means when it raises the risk)
FEATURES: list[tuple[str, str]] = [
    ("host_length", "The address is unusually long"),
    ("name_length", "The site's name is unusually long"),
    ("subdomain_levels", "The address has many parts before the site's name"),
    ("subdomain_length", "Long text before the site's name"),
    ("digits", "The address has many numbers in it"),
    ("digit_ratio", "Much of the address is numbers"),
    ("hyphens", "The address has many hyphens"),
    ("name_entropy", "The site's name looks random"),
    ("vowel_ratio", "The site's name is hard to pronounce"),
    ("longest_consonant_run", "The site's name has long runs of consonants"),
    ("letter_digit_switches", "Letters and numbers are mixed together"),
    ("is_ip", "The address is a raw IP number, not a name"),
    ("punycode", "The address uses encoded international characters"),
    ("risky_tld", "It ends in a domain ending often used for abuse"),
    ("uncommon_tld", "It ends in an uncommon domain ending"),
    ("tld_length", "It has an unusual domain ending"),
    ("free_host", "It's on a free hosting service where anyone can make a site"),
    ("bait_words", "The address contains words like login, verify or account"),
    ("brand_not_official", "The address mentions a known brand but doesn't belong to it"),
    ("lookalike", "The address imitates a known brand's name"),
]
NAMES = [n for n, _ in FEATURES]
REASONS = dict(FEATURES)


def hostname(url: str) -> str:
    """Lowercase hostname without "www.", from a full link or a bare domain."""
    text = url.strip()
    if "://" not in text:
        text = "http://" + text
    host = (urlsplit(text).hostname or "").rstrip(".").lower()
    return host[4:] if host.startswith("www.") else host


def entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    return -sum(c / len(text) * math.log2(c / len(text)) for c in counts.values())


def features(url: str) -> list[float]:
    host = hostname(url)
    try:
        ipaddress.ip_address(host.strip("[]"))
        is_ip = 1.0
    except ValueError:
        is_ip = 0.0
    parts = _public(host)
    name, suffix, sub = parts.domain, parts.suffix, parts.subdomain
    registrable = registrable_domain(host)   # owner-aware: foo.netlify.app is its own site
    free = any(host == f or host.endswith("." + f) for f in FREE_HOSTS)
    letters = [c for c in name if c.isalpha()]
    consonant_runs = re.findall(r"[bcdfghjklmnpqrstvwxz]+", name)
    official = official_brand(registrable) is not None
    values = {
        "host_length": len(host),
        "name_length": len(name),
        "subdomain_levels": len(sub.split(".")) if sub else 0,
        "subdomain_length": len(sub),
        "digits": sum(c.isdigit() for c in host),
        "digit_ratio": sum(c.isdigit() for c in host) / max(len(host), 1),
        "hyphens": host.count("-"),
        "name_entropy": entropy(name),
        "vowel_ratio": sum(c in "aeiou" for c in letters) / max(len(letters), 1),
        "longest_consonant_run": max((len(r) for r in consonant_runs), default=0),
        "letter_digit_switches": len(re.findall(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", host)),
        "is_ip": is_ip,
        "punycode": float("xn--" in host),
        "risky_tld": float(suffix.split(".")[-1] in RISKY_TLDS),
        "uncommon_tld": float(suffix not in COMMON_TLDS),
        "tld_length": len(suffix),
        "free_host": float(free),
        "bait_words": sum(w in host for w in BAIT_WORDS),
        "brand_not_official": float(not official and any(b in host for b in BRAND_WORDS)),
        "lookalike": float(not official and lookalike_brand(host) is not None),
    }
    return [float(values[n]) for n in NAMES]
