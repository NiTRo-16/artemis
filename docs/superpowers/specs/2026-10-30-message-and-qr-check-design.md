# Message check and QR check

Status: proposed, 30 October 2026

## Goal

Replace the "coming soon" pages at `/messages` and `/qr` with working tools:

- **Message check:** paste an SMS or WhatsApp message. Artemis names the scam script it recognises, quotes
  the wording that gave it away, and checks every link and UPI ID in the message.
- **QR check:** upload a screenshot of a QR code. Artemis shows what the code really does (who gets paid,
  how much, or where the link goes) and runs the matching check.

Both reuse the existing scan queue and UPI check. Neither stores what the person pastes or uploads.

## Decisions already made

- Scam wording is recognised by written rules. A trained model can be added later if there is a lawful
  source of labelled messages.
- The rules cover English and Hinglish (Hindi in English letters). Devanagari is out of scope for now.

## Message check

### Backend: `messages.py` and `POST /api/messages`

Request: `{"text": string}`, at most 2,000 characters. Rate limit: 30 a minute per network, with its own
limiter. The endpoint does no network work, so it answers immediately in the API process.

**1. Extracting items**

| Kind | Recognised | Rules |
|---|---|---|
| Link | `http(s)://`, `www.`, and bare domains (`sbi-kyc.top/pan`) | Disguised forms are undone: `hxxp`, `[.]`, `(dot)`. Trailing punctuation is removed. Validated with `scanner.normalize_domain`. At most 5, in order |
| UPI ID | `name@handle` and `upi://` links | The handle must be a known UPI handle, so email addresses aren't mistaken for UPI IDs. Checked with the existing `check_upi` |
| Phone | Indian mobile numbers (with or without +91) and 1800 numbers | Listed only. Artemis can't tell who owns a number, and says so |

Repeats are removed. Email addresses are ignored.

**2. Recognising scam scripts**

A table of scripts, each with a name, English and Hinglish patterns, a plain explanation, and strength:

| Script | Example wording | Strength |
|---|---|---|
| Account block or KYC | "account will be blocked", "KYC expired", "khata band ho jayega" | Strong |
| Electricity cut-off | "power will be disconnected tonight", "bijli kat jayegi" | Strong |
| Parcel or customs fee | "parcel held, pay customs fee", "address incomplete" | Strong |
| Digital arrest or police threat | "arrest warrant", "CBI", "illegal parcel in your name" | Strong |
| Pay to receive | "pay Rs 1 to receive refund", "refund ke liye PIN daalein" | Strong |
| Prize or lottery | "you have won", "lucky draw", "lottery lagi hai" | Strong |
| Asks for a secret | "share your OTP", "OTP batayein", "enter your PIN" | Strong |
| Screen-sharing app | "install AnyDesk", "TeamViewer", "QuickSupport" | Strong |
| App from a link | a link ending in `.apk`, "download this APK" | Strong |
| Job or task offer | "earn Rs 5000 daily", "like videos and earn", "ghar baithe kamai" | Medium |
| Investment or trading | "guaranteed returns", "double your money" | Medium |
| Easy loan | "instant loan approved", "no documents" | Medium |
| Family emergency | "I'm in hospital, send money to this number" | Medium |
| Pressure wording | "immediately", "within 24 hours", "turant", "abhi" | Weak: only raises a level already found |

Rules against false alarms, because genuine alerts look similar:

- A security warning is not a scam. "Your OTP is 482913. Do not share it with anyone" must stay clear:
  OTP wording counts only when the message asks for the code to be shared, not when it warns against it.
- A plain transaction alert ("Rs 500 debited from A/c XX1234") is clear.
- Wording alone never gives "danger" unless the script is strong. Pressure wording alone gives nothing.

**3. Response**

```json
{
  "level": "danger",
  "verdict": "Looks like an account block scam",
  "summary": "Banks don't block accounts by SMS or ask you to update PAN through a link.",
  "scripts": [{"id": "account_block", "title": "Account block threat", "explanation": "...", "strength": "strong"}],
  "matches": [{"start": 40, "end": 53, "script": "account_block"}],
  "items": [
    {"kind": "link", "value": "sbi-kyc-update.example/pan"},
    {"kind": "upi", "value": "sample.refund@upi", "payment": {"level": "danger", "verdict": "..."}},
    {"kind": "phone", "value": "+91 90000 00000"}
  ]
}
```

`level` covers the wording and UPI IDs: `clear`, `caution` (a medium script) or `danger`. `matches` gives
character positions, so the page highlights the words in the person's own text.

### Front end: `/messages`

- A large text box, a Check button, and "Messages aren't stored".
- The result shows the verdict, the message with suspicious words highlighted, and each script's
  explanation.
- Each item appears in a list. **Links start a normal scan through `/api/scans`** with live status and
  an "Open full report" link. These count towards the visitor's scan limit, and the most severe result
  raises the overall verdict.
- A clear result says "No known scam wording found" and never "safe": new scams use new wording.
- Advice for a risky result: don't click or pay, and the 1930 helpline and cybercrime.gov.in if money was lost.
- If someone pastes a whole message into the home page scan box, the box offers a link to Message check.

## QR check

### Decoding in the browser

The image is decoded by the `jsQR` library in the visitor's browser and **never uploaded**. The page accepts
a file chosen, dropped or pasted (PNG, JPG, WebP). Large images are scaled down, and if nothing is found it
retries at other sizes. Camera scanning is out of scope for this version.

### What happens to the decoded content

| Decoded content | What Artemis does |
|---|---|
| `upi://` link | Sends it to `/api/scans`, which checks it straight away, and shows pays to, name shown, amount and note. Always adds: "Scanning a QR and entering your PIN always sends money. You never need your PIN to receive money." |
| Web link | Shows the full address first, because a QR hides it, then runs a normal scan with live progress |
| Other text | Shows the text, says it's neither a link nor a payment, and offers Message check |
| Nothing readable | Says no QR code was found and suggests a sharper or cropped screenshot |

## Privacy

- Message text is processed in memory and never stored, logged or cached, and isn't added to history. The
  request body is not logged anywhere today, and this adds a test for it.
- QR images never leave the browser. Only the decoded content is sent, and only for checking.
- Links and UPI IDs found in a message follow the existing scan rules: results are kept 24 hours, and added
  to history for signed-in visitors.
- Scanning a link opens it in the sealed browser. A genuine one-time link could be used up by that, so the
  page says "Links in the message are opened in a sealed browser to check them."
- The privacy policy gains a short section saying all of the above, in the same change.

## Testing

- `tests/test_messages.py`: extraction (including disguised links, and emails not taken as UPI IDs) and each
  script in English and Hinglish.
- A labelled set in `tests/data/messages.jsonl`, written by hand: scam messages for every script, and genuine
  ones (OTPs, debit alerts, delivery updates, appointment reminders, ordinary chat). The test reports
  detection and false alarms, and fails on any false "danger" in the genuine set.
- These numbers show the rules do what they were written to do. They are not a measure of real-world accuracy,
  and the page and report must not present them as one.
- Vitest: highlighting from `matches`, and QR decoding of real generated QR images (UPI, link, text, none).
- Browser checks at desktop and phone width, in both themes.

## Out of scope

Reporting a message (it would need storing text), Devanagari, screenshots of messages (OCR), camera scanning,
phone number reputation, and a trained model.
