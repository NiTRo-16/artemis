"""The scanner reports each check as it finishes. Network calls are replaced, so this runs offline."""
import asyncio
import os

os.environ.setdefault("REDIS_URL", "fake://")
import impersonation  # noqa: E402
import scanner  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def collect(target):
    events = []

    async def progress(step, status):
        events.append((step, status))
    report = await scanner.scan(target, progress=progress)
    return report, events


async def unresolvable(host):
    raise scanner.Unresolvable("no address")


async def records(host, link=None):
    return {"registration": None, "certificate": None, "lists": []}

scanner.resolve_public = unresolvable
impersonation.lookup_records = records   # check_impersonation (used for unreachable sites) calls this

report, events = asyncio.run(collect("offline-site.example"))
ok("an unreachable site reports resolve as bad", ("resolve", "bad") in events)
ok("and still reports the impersonation check", any(step == "impersonation" for step, _ in events))
ok("the report itself is unchanged", report["resolves"] is False)


async def public(host):
    return ["203.0.113.5"]


async def tls(host, ip):
    return scanner.Category("tls", "Certificate", score=100)


async def email(host):
    return scanner.Category("email", "Email", score=40)


async def no_page(*args):
    return None

scanner.resolve_public = public
scanner.check_tls = tls
scanner.check_email = email
scanner.try_fetch = no_page
scanner.render_page = no_page
scanner.lookup_records = records

report, events = asyncio.run(collect("reachable-site.example"))
steps = dict(events)
ok("resolve ok", steps.get("resolve") == "ok")
ok("a good certificate is ok", steps.get("certificate") == "ok")
ok("weak email records are bad", steps.get("email") == "bad")
ok("records done", steps.get("records") == "done")
ok("a page that didn't load is skipped", steps.get("page") == "skipped")
ok("impersonation reported last", events[-1][0] == "impersonation")


async def broken(step, status):
    raise RuntimeError("Redis went away")

ok("a failing progress callback doesn't fail the scan",
   asyncio.run(scanner.scan("reachable-site.example", progress=broken))["domain"] == "reachable-site.example")
print(f"\n{sum(results)}/{len(results)} passed")
