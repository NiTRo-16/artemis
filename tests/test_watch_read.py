"""Domain watch: reading certificate log tiles, and matching names against brands."""
import time
from datetime import date, timedelta
from pathlib import Path

import ct_logs
import watch_match
from ct_fixture import der, leaf, tbs

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


# ---------- tile paths ----------
ok("tile path, small", ct_logs.tile_path(5) == "005")
ok("tile path, thousands", ct_logs.tile_path(1234) == "x001/234")
ok("tile path, millions", ct_logs.tile_path(4105756) == "x004/x105/756")
ok("checkpoint size", ct_logs.parse_checkpoint("origin/log\n1179593\nabc=\n\n— sig\n") == 1179593)

# ---------- entries ----------
entries, bad = ct_logs.parse_tile(leaf(["a.example.com", "*.b.example.org"]) + leaf(["c.example.net"], precert=False))
ok("reads a precertificate and a certificate", [e.names for e in entries] == [["a.example.com", "*.b.example.org"], ["c.example.net"]])
ok("reads the timestamp", entries[0].timestamp_ms == 1_800_000_000_000 and bad == 0)

good = leaf(["a.example.com"])
entries, bad = ct_logs.parse_tile(good + good[:40])
ok("truncated entry: keeps what came before, counts it", len(entries) == 1 and bad == 1)
entries, bad = ct_logs.parse_tile(b"\xff" * 300)
ok("garbage counted, not fatal", entries == [] and bad == 1)
ok("length past the end is refused", ct_logs.names_from_tbs(b"\x30\x84\xff\xff\xff\xff") == [])
ok("deep garbage gives no names", ct_logs.names_from_tbs(der(0x30, der(0xA0, b"\xff\xff"))) == [])
ok("non-text name skipped", ct_logs.names_from_tbs(tbs(["ok.example.com", "badé.example.com"])) == ["ok.example.com"])

# A real tile saved from Let's Encrypt's Sycamore 2026h2 log, cut to its first entries.
sample = Path(__file__).parent / "data" / "ct_tile_sample.bin"
entries, bad = ct_logs.parse_tile(sample.read_bytes())
ok(f"real tile sample parses ({len(entries)} entries, {bad} bad)", len(entries) >= 15 and bad == 0)
# Certificates for IP addresses have no DNS names; the first two in this sample are those.
ok("real entries have plausible names", sum(bool(e.names) for e in entries) == 18 and all("." in n for e in entries for n in e.names))
ok("real timestamps are this decade", all(1_700_000_000_000 < e.timestamp_ms < 2_000_000_000_000 for e in entries))

# ---------- shards: fails when the list needs its next half-year added ----------
latest = max(end for _, _, end in ct_logs.LOGS)
ok("configured logs cover certificates issued now", latest >= (date.today() + timedelta(days=100)).isoformat())

# ---------- matching ----------
m = watch_match.match


def brand(host):
    hit = m(host)
    return hit and hit.brand

ok("contains a long brand name", brand("hdfcbank-kyc.xyz") == "HDFC Bank")
ok("exact long name elsewhere", brand("phonepe.shop") == "PhonePe")
ok("wildcard stripped", m("*.paytm-refund.top").host == "paytm-refund.top")
ok("lookalike characters", brand("paypa1-login.com") == "PayPal")
ok("one typo in a long name", brand("razorpey.com") == "Razorpay")
ok("subdomain copying a brand", brand("hdfcbank.login-now.com") == "HDFC Bank")
ok("official domain skipped", m("www.hdfcbank.com") is None)
ok("official bank.in domain skipped", m("onlinesbi.sbi.bank.in") is None)
ok("unrelated name skipped", m("www.gardening-tips.org") is None)
ok("registrable domain stored", m("secure.login.hdfcbank-kyc.xyz").registrable == "hdfcbank-kyc.xyz")
ok("short keyword alone isn't enough", m("sbi.com.example.org") is None and m("visa-consultants.com") is None)
ok("short keyword inside a word isn't a match", m("sbi-login".replace("sbi", "busbin") + ".com") is None)
ok("short keyword plus a clue word counts", brand("sbi-kyc-update.com") == "State Bank of India")
ok("short keyword plus a risky ending counts", brand("sbi-online.xyz") == "State Bank of India")
ok("short-name typos need a clue", m("phase.com") is None and m("chose.org") is None)
ok("empty and odd names don't crash", m("") is None and m("*.") is None and m("localhost") is None and m("xn--é.com") is None)

# Found by reading real names from the logs on 30 October 2026.
for host in ("pianoledger.com", "energy-outlook.org", "outlook.gworld.net", "virtualcloud.co.in", "leder.nu", "outloop.pl", "finance.ae.org", "658125.xyz", "h65bl.top", "icicn.com", "gewa.icivi.vn", "pay77.click", "cp.hdfc.bank.in",
             "test.acm.eusc-de-east-1.amazonaws.eu", "cloudauth.jkss.create-burner.amazon.dev", "payment.gateway.elb.prod.ride.use1.aws.rezos.io",
             "vex.ppim.aws.porsche-preview.cloud"):
    ok(f"innocent, from the logs: {host}", m(host) is None)
for host in ("facebook-login-urgent-verify.org.ph", "paypal-com.celebsplay.com", "support.zoom.us.idvip1.tokovpn.com",
             "www.icloud.com.falk-ngr.metropoly.ir", "app.binance-secure.com", "trezor-io-strt-ass.pages.dev"):
    ok(f"suspicious, from the logs: {host}", m(host) is not None)
ok("distinctive Indian names need no clue", brand("hdfc-loans.in") == "HDFC Bank" and brand("paytm-offers.in") == "Paytm")
for host in ("www.incometaxindia.co", "dqmappuat.icicibankltd.com", "icic1-login.top"):
    ok(f"Indian lookalike still caught: {host}", m(host) is not None)
ok("a loose word plus a clue still counts", brand("ledger-secure.com") == "Ledger")
ok("a real address needs something after it", m("www.zoom.us") is None)

names = [f"host{i}.some-random-site{i}.example.com" for i in range(20000)]
start = time.perf_counter()
for name in names:
    m(name)
each = (time.perf_counter() - start) / len(names) * 1e6
ok(f"fast enough: {each:.0f} microseconds a name (target 50)", each < 50)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
