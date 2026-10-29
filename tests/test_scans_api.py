"""The queue-based scan API, run with the job executed inside the API process (inline mode)."""
import json

import testenv  # noqa: F401
from fastapi.testclient import TestClient  # noqa: E402

import jobs  # noqa: E402
import main  # noqa: E402
import worker  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


async def fake_scan(target, progress=None):
    await progress("certificate", "ok")
    await progress("impersonation", "ok")
    return {"domain": target, "risk": {"score": 5, "label": "Low"},
            "impersonation": {"verdict": "No impersonation signs"}, "payment": None}

worker.scan = fake_scan


def read_events(client, job_id):
    events = []
    with client.stream("GET", f"/api/scans/{job_id}/events") as resp:
        ok("events are a server-sent event stream", resp.headers["content-type"].startswith("text/event-stream"))
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


with TestClient(main.app, base_url="http://testserver") as c:
    main.scan_limiter.reset()
    r = c.post("/api/scans", json={"target": "site-one.example"})
    ok("a new scan is accepted with 202 and a job id", r.status_code == 202 and r.json()["status"] == "queued")
    job_id = r.json()["id"]
    events = read_events(c, job_id)
    ok("progress events arrive in order",
       [e.get("step") for e in events if e["type"] == "step"] == ["certificate", "impersonation"])
    ok("the stream ends with the full report",
       events[-1]["type"] == "done" and events[-1]["report"]["domain"] == "site-one.example")
    ok("the job can also be read directly", c.get(f"/api/scans/{job_id}").json()["status"] == "done")
    ok("events for a finished job replay at once", read_events(c, job_id)[-1]["type"] == "done")

    again = c.post("/api/scans", json={"target": "site-one.example"})
    ok("the same target again returns the saved result",
       again.status_code == 200 and again.json() == {"id": job_id, "status": "done"})

    ok("an invalid target is refused", c.post("/api/scans", json={"target": "not a domain"}).status_code == 400)
    upi = c.post("/api/scans", json={"target": "upi://pay?pa=shop.name@okaxis&pn=Shop"})
    ok("a UPI link is checked straight away", upi.status_code == 200 and upi.json()["report"]["payment"] is not None)
    ok("an unknown job is 404", c.get("/api/scans/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404)
    ok("a malformed job id is 404", c.get("/api/scans/not*a*job").status_code == 404)

    shared = c.post(f"/api/scans/{job_id}/share")
    ok("a finished scan can be shared", shared.status_code == 200 and shared.json() == {"url": f"/r/{job_id}"})
    ok("the shared result can be read back", c.get(f"/api/shared/{job_id}").json()["domain"] == "site-one.example")
    ok("the share page loads", c.get(f"/r/{job_id}").status_code == 200)
    ok("an unknown shared result is 404", c.get("/api/shared/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404)

    old = c.post("/api/scan", json={"domain": "site-two.example"})
    ok("the old endpoint still returns the report directly",
       old.status_code == 200 and old.json()["domain"] == "site-two.example")

    jobs.MAX_QUEUED = 0
    ok("a full queue answers 503", c.post("/api/scans", json={"target": "site-three.example"}).status_code == 503)
    jobs.MAX_QUEUED = 200
    ok("healthz is ok", c.get("/healthz").json() == {"status": "ok"})
print(f"\n{sum(results)}/{len(results)} passed")
