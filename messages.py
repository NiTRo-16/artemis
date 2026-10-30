"""The message check: known scam scripts in a pasted SMS or WhatsApp message, and the links, UPI IDs and
phone numbers in it.

The text is only read here, in memory. It's never stored, logged or sent anywhere, and nothing is fetched:
the page scans the links it gets back through the normal scan queue.

Scripts are written rules, in English, Hinglish and Hindi, because every one must be able to say why it fired.
Genuine alerts look a lot like scams ("Your OTP is 4432, do not share it"), so a false alarm is treated as
a bug: tests/data/messages.jsonl holds genuine messages that must stay clear. A clear result only means no
known wording was found, so it must never be worded as "safe".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from impersonation import RISKY_TLDS, _extract
from payments import UPI_ID, check_upi
from scanner import ScanError, normalize_domain

MAX_TEXT = 2000
MAX_LINKS = 5
FLAGS = re.IGNORECASE | re.DOTALL

# Banks' own handles and the apps' (payments.UPI_APPS lists only the apps whose names it shows). A handle
# has to be known here, so that "a@home" in a message isn't taken for a UPI ID.
UPI_HANDLES = {
    "ybl", "ibl", "axl", "okaxis", "okhdfcbank", "okicici", "oksbi", "paytm", "ptyes", "ptaxis", "pthdfc", "ptsbi",
    "apl", "yapl", "upi", "sbi", "hdfcbank", "icici", "axisbank", "axisb", "kotak", "kmbl", "pnb", "boi", "barodampay",
    "freecharge", "waaxis", "wahdfcbank", "wasbi", "waicici", "idfcbank", "idfcfirst", "indus", "rbl", "yesbank", "yesbankltd",
    "federal", "aubank", "hsbc", "sc", "citi", "dbs", "mahb", "cnrb", "unionbank", "uboi", "ikwik", "jupiteraxis", "fbl",
}
# Bare words only count as a site when the ending is one people actually type, or the name doesn't look
# like two words of a sentence missing a space ("now.Click").
COMMON_ENDINGS = {"com", "in", "co.in", "net", "org", "info", "biz", "co", "io", "me", "live", "online", "site", "shop", "store",
                  "app", "xyz", "ac.in", "gov.in", "org.in", "net.in", "bank.in"} | RISKY_TLDS
EDGE_PUNCTUATION = ".,;:!?\"'()[]{}<>*"
DISGUISED_DOT = re.compile(r"\s*(?:\[\.\]|\(\.\)|\[dot\]|\(dot\))\s*", re.IGNORECASE)
LINK_START = re.compile(r"(?:hxxps?://|https?://|www\.|upi://)", re.IGNORECASE)
BARE_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}(?:/\S*)?$")
PHONE = re.compile(r"(?<![\d.])(?:(?:\+91|91)[\s-]?[6-9]\d{4}[\s-]?\d{5}|[6-9]\d{4}[\s-]?\d{5}|1800[\s-]?\d{3}[\s-]?\d{3,4})(?![\d])")


def _is_bare_site(token: str) -> bool:
    if not BARE_DOMAIN.match(token):      # lower case, or whole token upper case (checked by the caller)
        return False
    host = token.split("/", 1)[0]
    suffix = _extract(host).suffix
    if not suffix:
        return False
    return suffix in COMMON_ENDINGS or "/" in token or "-" in host


def extract_items(text: str) -> list[dict]:
    """Links, UPI IDs and phone numbers, in order and without repeats."""
    plain = DISGUISED_DOT.sub(".", text)
    items: list[dict] = []
    seen: set[str] = set()
    links = 0
    remaining: list[str] = []

    def add(kind: str, value: str) -> None:
        if value.lower() not in seen:
            seen.add(value.lower())
            items.append({"kind": kind, "value": value})

    for raw in plain.split():
        token = raw.strip(EDGE_PUNCTUATION)
        start = LINK_START.search(token)
        if start:
            token = token[start.start():]
            if token.lower().startswith("upi://"):
                add("upi", token)
                continue
            token = re.sub(r"^hxxp", "http", token, flags=re.IGNORECASE)
            try:
                normalize_domain(token)
            except ScanError:
                continue
            if links < MAX_LINKS and token.lower() not in seen:
                links += 1
                add("link", token)
        elif "@" in token:
            if UPI_ID.match(token) and token.rsplit("@", 1)[1].lower() in UPI_HANDLES:
                add("upi", token)
        elif (token.islower() or token.isupper() or not any(c.isupper() for c in token)) and _is_bare_site(token.lower()):
            value = token.lower()
            try:
                normalize_domain(value)
            except ScanError:
                continue
            if links < MAX_LINKS and value not in seen:
                links += 1
                add("link", value)
        else:
            remaining.append(raw)
    for match in PHONE.finditer(" ".join(remaining)):
        add("phone", match.group(0))
    return items


# ---------- scam scripts ----------

@dataclass(frozen=True)
class Script:
    id: str
    title: str
    verdict: str
    explanation: str
    strength: str                     # "strong" gives danger, "medium" gives caution
    patterns: tuple[str, ...]
    unless: str | None = None         # in the same sentence, this means it's not the scam (a warning, a genuine notice)


# In a sentence, these mean the message is warning people about the scam, not running it.
WARNING_ABOUT_SCAMS = re.compile(r"\b(beware|be aware|be careful|fraud alert|scam alert|awareness|savdhan|sawdhan|never ask|will never)\b"
                                 r"|सावधान|सतर्क|कभी नहीं|कभी न ", FLAGS)

# Hindi patterns are plain substrings: Hindi vowel signs aren't word characters, so \\b would split words.
SCRIPTS = (
    Script("account_block", "Account block or KYC threat", "Looks like an account block scam",
           "Banks don't block accounts by message or ask you to update KYC or PAN through a link. "
           "The threat is there to rush you into entering your details on a fake page.", "strong",
           (r"\b(?:accounts?|a/c|acct|netbanking|net banking|yono|debit card|credit card|card|sim|khata|khaata)\b.{0,40}"
            r"\b(?:will be|has been|is being|getting|ho jayega|ho jaega|hoga)\b.{0,15}\b(?:block\w*|suspend\w*|deactivat\w*|clos\w*|freez\w*|band|expire\w*)",
            r"\b(?:accounts?|a/c|netbanking|net banking|yono|khata|khaata)\b.{0,30}\b(?:band ho|block ho|suspend ho)",
            r"\bkyc\b.{0,40}\b(?:expir\w*|pending|incomplete|suspend\w*|band\b)",
            r"\b(?:update|complete|verify)\b.{0,20}\b(?:kyc|pan|aadhaar)\b.{0,50}\b(?:block|suspend|band|immediately|turant|link|today|within|http)",
            r"(?:खाता|खाते|अकाउंट|केवाईसी|kyc|कार्ड|सिम|नेट ?बैंकिंग|योनो).{0,40}(?:बंद हो|बंद कर|ब्लॉक|निलंबित|सस्पेंड)",
            r"(?:केवाईसी|kyc|पैन|आधार).{0,30}(?:अपडेट|पूरा|पूरी|समाप्त|लंबित).{0,40}(?:तुरंत|आज|घंटे|बंद|ब्लॉक|लिंक|http)"),
           unless=r"\b(?:as per your request|as requested|your request|visit (?:your |the )?(?:nearest )?branch)\b|आपके अनुरोध|शाखा"),
    Script("electricity", "Electricity cut-off threat", "Looks like an electricity bill scam",
           "Electricity boards don't threaten to cut power tonight by SMS or ask you to call a mobile number. "
           "Check your bill on the board's official app or website.", "strong",
           (r"\b(?:electricity|power|bijli|light)\b.{0,40}\b(?:disconnect\w*|kat jayeg\w*|kaat\w*|cut off|band ho jayeg\w*)",
            r"\b(?:bill|connection)\b.{0,40}\bdisconnect\w*",
            r"(?:बिजली|कनेक्शन).{0,40}(?:कट जाएग|कट जाएगा|काट दी|काट दिया|काटा जाएगा|बंद हो जाएग|बंद कर दी)"),
           unless=r"\b(?:maintenance|scheduled|repair)\b|रखरखाव|मरम्मत|निर्धारित"),
    Script("parcel", "Parcel or customs fee", "Looks like a parcel fee scam",
           "Scammers pose as India Post or couriers and ask for a small fee to steal your card or UPI details. "
           "Check the tracking number on the courier's official site.", "strong",
           (r"\b(?:parcel|package|courier|shipment|consignment|india post|fedex|dhl|bluedart)\b.{0,70}"
            r"\b(?:held|on hold|stuck|customs?|fee|charges|incomplete|wrong address|undeliver\w*|rok\w*)\b",
            r"(?:पार्सल|पैकेज|कूरियर|इंडिया पोस्ट|शिपमेंट).{0,70}(?:रोक|रुका|अटक|कस्टम|शुल्क|फीस|अधूरा|गलत पता)")),
    Script("digital_arrest", "Police or digital arrest threat", "Looks like a digital arrest scam",
           "Police, CBI and customs never arrest anyone over a call or ask for money to clear a case. "
           "\"Digital arrest\" doesn't exist. Hang up and call 1930.", "strong",
           (r"\bdigital arrest\b", r"\barrest warrant\b", r"\bgiraftar\w*\b",
            r"\b(?:cbi|police|customs|narcotics|cyber ?crime|enforcement directorate)\b.{0,80}"
            r"\b(?:arrest\w*|warrant|illegal|legal action|seized|case (?:darj|registered|filed))\b",
            r"डिजिटल अरेस्ट|गिरफ्तार|गिरफ़्तार",
            r"(?:सीबीआई|पुलिस|कस्टम|नारकोटिक्स|साइबर क्राइम|प्रवर्तन निदेशालय).{0,80}(?:वारंट|मामला दर्ज|केस दर्ज|अवैध|जब्त|ज़ब्त|कानूनी कार्रवाई)")),
    Script("pay_to_receive", "Pay to receive money", "Looks like a refund scam",
           "Nobody needs you to pay or enter your UPI PIN to give you money. "
           "A PIN is only ever used to send money out of your account.", "strong",
           (r"\b(?:pay|send|transfer)\b.{0,30}\b(?:to|for|and)\b.{0,30}\b(?:receive|get|claim)\b.{0,30}\b(?:refund|cash ?back|money|prize|reward|payment)",
            r"\brefund\b.{0,40}\b(?:pay|pin|processing fee)\b", r"\brefund ke liye\b",
            r"\b(?:enter|daal\w*|dal\w*)\b.{0,20}\bpin\b.{0,30}\b(?:receive|refund|paisa|get|claim|milega)",
            r"रिफंड.{0,40}(?:पिन|भुगतान करें|शुल्क|पे करें)", r"रिफंड के लिए", r"रिफंड पाने",
            r"(?:पिन|pin).{0,30}(?:डालें|डालिए|दर्ज).{0,30}(?:रिफंड|पैसा|पैसे|मिल|प्राप्त)",
            r"(?:पाने|प्राप्त करने) के लिए.{0,30}(?:भुगतान|पिन|pin)")),
    Script("prize", "Prize or lottery", "Looks like a prize scam",
           "You can't win a contest you never entered, and a real prize never needs a fee or your bank details.", "strong",
           (r"\byou(?:'ve| have)? won\b", r"\bcongratulations\b.{0,60}\b(?:won|winner|selected|prize|reward)\b",
            r"\blucky draw\b", r"\blottery\b", r"\bjackpot\b", r"\binaam\b", r"\bjeet\w* (?:hai|gaye|gayi)\b",
            r"लॉटरी|जैकपॉट|लकी ड्रॉ|इनाम|पुरस्कार राशि", r"आपने.{0,40}जीत", r"बधाई.{0,60}(?:जीत|विजेता|चुने|पुरस्कार)")),
    Script("asks_secret", "Asks for a code or PIN", "This message asks for a secret code",
           "An OTP, PIN or CVV is like the key to your account. Banks and support staff never ask for it, "
           "and anyone who does is trying to take your money.", "strong",
           (r"\b(?:share|send|tell|give|forward|provide)\b.{0,30}\b(?:otp|cvv|upi pin|atm pin|password)\b",
            r"\b(?:otp|cvv|pin)\b.{0,25}\b(?:batayen|batayein|batao|bhejo|bhejein|bhejiye|de do|dijiye|share kar\w*)\b",
            r"(?:otp|cvv|ओटीपी|सीवीवी|पिन|pin|पासवर्ड).{0,25}(?:बताएं|बताएँ|बताइए|बताओ|भेजें|भेजिए|भेजो|दीजिए|शेयर कर)"),
           unless=r"\b(?:do not|don'?t|never|not to|mat|na kare\w*|nahi|delivery|rider|driver|captain)\b"
                  r"|मत |न करें|नहीं|न दें|न बताएं|न बताएँ|डिलीवरी"),
    Script("screen_share", "Asks you to install a screen-sharing app", "This message asks you to share your screen",
           "AnyDesk and similar apps let the other person see and control your phone, including your banking apps. "
           "Support staff never need them.", "strong",
           (r"\b(?:install|download|open|kholo|daal\w*)\b.{0,30}\b(?:any ?desk|team ?viewer|quick ?support|rust ?desk)\b",
            r"\b(?:any ?desk|team ?viewer|quick ?support|rust ?desk)\b.{0,30}\b(?:install|download|kar\w*|code)\b",
            r"(?:एनीडेस्क|टीमव्यूअर|any ?desk|team ?viewer).{0,30}(?:इंस्टॉल|डाउनलोड|खोल|कोड)",
            r"(?:इंस्टॉल|डाउनलोड).{0,30}(?:एनीडेस्क|टीमव्यूअर|any ?desk|team ?viewer)")),
    Script("app_link", "App sent as a file", "This message sends an app to install",
           "Real apps come from the Play Store. An .apk file from a message can read your SMS codes and empty your account. "
           "Don't install it.", "strong",
           (r"\.apk\b", r"\b(?:download|install)\b.{0,20}\bapk\b", r"\bapk\b.{0,20}\b(?:download|install)\b",
            r"(?:एपीके|apk).{0,25}(?:डाउनलोड|इंस्टॉल)", r"(?:डाउनलोड|इंस्टॉल).{0,25}(?:एपीके|apk)")),
    Script("job", "Easy money job offer", "This looks like a job scam",
           "Paid tasks like liking videos are a common trap: they pay a little at first, then ask you to \"invest\" to get paid more.", "medium",
           (r"\b(?:earn|kamai|income|kamaye\w*)\b.{0,30}(?:\bdaily\b|\bper day\b|\brs\b|₹|\bghar\b|\bhome\b|\bpart.?time\b|\broz\b)",
            r"\b(?:like|subscribe|rate)\b.{0,40}\b(?:earn|get paid|paid)\b", r"\bghar baithe\b", r"\bpart.?time job\b",
            r"घर बैठे", r"पार्ट.?टाइम (?:नौकरी|जॉब)", r"(?:कमाएं|कमाएँ|कमाई|कमाइए).{0,30}(?:रोज|प्रतिदिन|रुपये|₹|घर)",
            r"(?:लाइक|सब्सक्राइब).{0,40}(?:कमाएं|कमाएँ|कमाई|पैसे)")),
    Script("investment", "Guaranteed investment", "This looks like an investment scam",
           "Nobody can guarantee returns. Check that any adviser is registered with SEBI before you send money.", "medium",
           (r"\bguaranteed (?:returns?|profit)\b", r"\bdouble your money\b", r"\bpaisa double\b",
            r"\b\d+\s?% (?:daily|weekly|monthly) (?:returns?|profit)\b",
            r"गारंटी.{0,20}(?:रिटर्न|मुनाफा|मुनाफ़ा|लाभ)", r"(?:पैसा|पैसे|रकम).{0,15}(?:डबल|दोगुना|दोगुने)")),
    Script("loan", "Too-easy loan", "This looks like a loan scam",
           "Loans with no documents often turn into a demand for fees up front, or an app that harasses you. "
           "Check that the lender is listed by the RBI.", "medium",
           (r"\b(?:instant|easy|pre.?approved)\b.{0,15}\bloan\b", r"\bloan\b.{0,30}\b(?:no documents?|without documents?|bina document\w*)\b",
            r"(?:तुरंत|आसान|प्री.?अप्रूव्ड|बिना दस्तावेज|बिना कागज).{0,20}(?:लोन|ऋण)", r"(?:लोन|ऋण).{0,30}(?:बिना दस्तावेज|बिना कागज)")),
    Script("family", "Someone you know needs money", "This could be someone pretending to be family",
           "Scammers pose as relatives with a new number and an emergency. Call them on the number you already have before sending anything.", "medium",
           (r"\b(?:in hospital|accident|emergency|hospital mein|new number|naya number)\b.{0,70}\b(?:send|money|paise|bhej\w*|transfer)\b",
            r"(?:अस्पताल|दुर्घटना|एक्सीडेंट|इमरजेंसी|नया नंबर|नए नंबर).{0,70}(?:पैसे|भेज|ट्रांसफर)")),
)
PRESSURE = re.compile(r"\b(?:immediately|urgent(?:ly)?|within \d+ (?:hours?|hrs?|minutes?)|last chance|act now|today only|turant|abhi|jaldi|aaj hi)\b|तुरंत|अभी|जल्दी|आज ही", FLAGS)
_COMPILED = tuple((script, tuple(re.compile(p, FLAGS) for p in script.patterns),
                   re.compile(script.unless, FLAGS) if script.unless else None) for script in SCRIPTS)
SENTENCE_END = re.compile(r"[!?\n।]|\.(?=\s)")
RANK = {"clear": 0, "caution": 1, "danger": 2}


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence around a match, to read what it says about the wording found."""
    before = [m.end() for m in SENTENCE_END.finditer(text, 0, start)]
    after = SENTENCE_END.search(text, end)
    return text[before[-1] if before else 0:after.start() if after else len(text)]


def _find_scripts(text: str) -> tuple[list[Script], list[dict]]:
    found: list[Script] = []
    matches: list[dict] = []
    for script, patterns, unless in _COMPILED:
        hits = []
        for pattern in patterns:
            for match in pattern.finditer(text):
                sentence = _sentence(text, match.start(), match.end())
                if WARNING_ABOUT_SCAMS.search(sentence) or (unless and unless.search(sentence)):
                    continue
                hits.append(match)
        if hits:
            found.append(script)
            matches += [{"start": m.start(), "end": m.end(), "script": script.id} for m in hits]
    if found:
        matches += [{"start": m.start(), "end": m.end(), "script": "pressure"} for m in PRESSURE.finditer(text)]
    matches.sort(key=lambda m: (m["start"], m["end"]))
    return found, matches


def check_message(text: str) -> dict:
    """What's wrong with a message. Nothing here keeps the text or contacts anything."""
    items = extract_items(text)
    worst_upi = None
    for item in items:
        if item["kind"] == "upi":
            try:
                payment = check_upi(item["value"])
            except ValueError:
                continue
            item["payment"] = {"level": payment["level"], "verdict": payment["verdict"], "summary": payment["summary"]}
            if worst_upi is None or RANK[payment["level"]] > RANK[worst_upi["level"]]:
                worst_upi = payment
    scripts, matches = _find_scripts(text)
    scripts.sort(key=lambda s: s.strength != "strong")
    level = "danger" if any(s.strength == "strong" for s in scripts) else "caution" if scripts else "clear"
    if worst_upi and RANK[worst_upi["level"]] > RANK[level]:
        level = worst_upi["level"]
    if scripts:
        verdict, summary = scripts[0].verdict, scripts[0].explanation
    elif worst_upi and level != "clear":
        verdict, summary = worst_upi["verdict"], worst_upi["summary"]
    else:
        verdict = "No known scam wording found"
        summary = "This doesn't match the scams Artemis knows, but new scams use new wording. If you weren't expecting it, " \
                  "check with the sender another way, and don't enter a PIN or OTP."
    return {
        "level": level,
        "verdict": verdict,
        "summary": summary,
        "scripts": [{"id": s.id, "title": s.title, "explanation": s.explanation, "strength": s.strength} for s in scripts],
        "matches": matches,
        "items": items,
    }
