"""The message check: what it extracts, the scam scripts it recognises, and that nothing is kept."""
import json
import logging
from pathlib import Path

import testenv  # noqa: F401
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import store  # noqa: E402
from messages import MAX_LINKS, check_message, extract_items  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def values(text, kind):
    return [i["value"] for i in extract_items(text) if i["kind"] == kind]


# --- extraction ---
ok("a full link", values("Go to https://sbi-kyc.example/pan now.", "link") == ["https://sbi-kyc.example/pan"])
ok("a link stuck to a word", values("Link:http://bad.example/x", "link") == ["http://bad.example/x"])
ok("www without a scheme", values("Visit www.bad-site.com, today", "link") == ["www.bad-site.com"])
ok("a bare domain with a path", values("Update at sbi-kyc.top/update.", "link") == ["sbi-kyc.top/update"])
ok("disguised links are undone", values("open hxxp://sbi-kyc[.]top/pan", "link") == ["http://sbi-kyc.top/pan"])
ok("(dot) is undone", values("visit sbi-kyc (dot) top", "link") == ["sbi-kyc.top"])
ok("the host after an @ trick is what's scanned", values("http://sbi.com@evil.example/", "link") == ["http://sbi.com@evil.example/"])
ok("a repeated link is listed once", len(values("a.example.com/x a.example.com/x", "link")) == 1)
ok("at most five links", len(values(" ".join(f"site{i}.com" for i in range(9)), "link")) == MAX_LINKS)
ok("sentences without spaces aren't links", values("Update now.Click here. Rs.500 paid.Thanks e.g. this", "link") == [])
ok("an amount isn't a link", values("Rs.4,999.00 credited", "link") == [])
ok("a known UPI ID", values("Pay to refund.desk@okaxis today", "upi") == ["refund.desk@okaxis"])
ok("a UPI link", values("upi://pay?pa=a.b@ybl&pn=Shop", "upi") == ["upi://pay?pa=a.b@ybl&pn=Shop"])
ok("an email address isn't a UPI ID", values("write to help@gmail.com or me@example.org", "upi") == [])
ok("an email address isn't a link", values("write to help@gmail.com", "link") == [])
ok("a mention isn't a UPI ID", values("thanks @rahul and a@home", "upi") == [])
ok("a mobile number", values("Call +91 90000 12345 now", "phone") == ["+91 90000 12345"])
ok("a 1800 number", values("Toll free 1800 123 4567.", "phone") == ["1800 123 4567"])
ok("an account number isn't a phone", values("A/c 123456789012 and OTP 5521", "phone") == [])

# --- every labelled message ---
rows = [json.loads(line) for line in (Path(__file__).parent / "data" / "messages.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
scams = [r for r in rows if not r.get("genuine")]
genuine = [r for r in rows if r.get("genuine")]
caught = 0
for row in scams:
    result = check_message(row["text"])
    found = {s["id"] for s in result["scripts"]}
    good = row["script"] in found and result["level"] == row.get("level", "danger")
    caught += good
    ok(f"{row['script']}: {row['text'][:50]}", good)
for row in genuine:
    result = check_message(row["text"])
    ok(f"genuine stays clear: {row['text'][:50]}", result["level"] == "clear" and not result["scripts"])
print(f"\nHand-written set: {caught}/{len(scams)} scam messages recognised, "
      f"{sum(check_message(r['text'])['level'] != 'clear' for r in genuine)}/{len(genuine)} genuine messages flagged\n")

# --- the response ---
text = "Your account will be blocked immediately. Pay to refund.desk@okaxis or visit bad.example.com/x"
result = check_message(text)
ok("a strong script gives danger with a verdict", result["level"] == "danger" and "account" in result["verdict"].lower())
ok("matches point at the words in the text", any("blocked" in text[m["start"]:m["end"]] for m in result["matches"]))
ok("pressure wording is highlighted once something is found", any(m["script"] == "pressure" for m in result["matches"]))
ok("items are returned", {i["kind"] for i in result["items"]} == {"link", "upi"})
ok("a UPI ID comes with its check", next(i for i in result["items"] if i["kind"] == "upi")["payment"]["level"] in ("clear", "caution", "danger"))
alone = check_message("Please reply immediately, turant!")
ok("pressure wording alone gives nothing", alone["level"] == "clear" and not alone["matches"] and not alone["scripts"])
ok("a clear result never says safe", "safe" not in (check_message("See you at 5")["verdict"] + check_message("See you at 5")["summary"]).lower())
scam_upi = check_message("Pay here: upi://pay?pa=a.b@ybl&tn=Refund")
ok("a dangerous UPI link raises the level on its own", scam_upi["level"] == "danger")
ok("a broken UPI link doesn't break the check", check_message("upi://pay?pa=nonsense")["level"] == "clear")
ok("a very long message of bad patterns finishes fast", check_message(("account " * 300)[:2000])["level"] == "clear")

# --- the endpoint keeps nothing ---
SECRET = "my-private-message-text-7719 your account will be blocked"


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


capture = Capture()
logging.getLogger().addHandler(capture)
logging.getLogger().setLevel(logging.DEBUG)
with TestClient(main.app, base_url="http://testserver") as c:
    main.message_limiter.reset()
    before = set(store.sync_client().keys("*"))
    r = c.post("/api/messages", json={"text": SECRET})
    ok("the endpoint answers", r.status_code == 200 and r.json()["level"] == "danger")
    ok("responses aren't cached", r.headers.get("cache-control") == "no-store")
    new_keys = set(store.sync_client().keys("*")) - before
    stored = "".join(str(store.sync_client().zrange(k, 0, -1)) if k.startswith("rl:") else str(store.sync_client().dump(k)) for k in new_keys)
    ok("the text isn't in Redis", "7719" not in "".join(new_keys) + stored)
    ok("only the rate limit was written", all(k.startswith("rl:message:") for k in new_keys))
    ok("the text isn't logged", not any("7719" in line for line in capture.lines))
    ok("an empty message is refused", c.post("/api/messages", json={"text": "   "}).status_code == 400)
    ok("too long a message is refused", c.post("/api/messages", json={"text": "a" * 2001}).status_code == 422)
    for _ in range(30):
        c.post("/api/messages", json={"text": "hello"})
    ok("the rate limit applies", c.post("/api/messages", json={"text": "hello"}).status_code == 429)
    main.message_limiter.reset()

print(f"\n{sum(results)}/{len(results)} passed")
