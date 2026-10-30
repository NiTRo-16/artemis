"""The name on an account, and the 404 page."""
import testenv  # noqa: F401
from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
import main  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


origin = {"Origin": "http://testserver"}
PASSWORD = "correct horse battery"

with TestClient(main.app) as client:
    res = client.post("/api/signup", json={"email": "asha@example.com", "password": PASSWORD, "name": "  Asha \n  Rao\x07 "}, headers=origin)
    user = db.user_by_email("asha@example.com")
    ok("sign-up stores the tidied name", res.status_code == 200 and user["name"] == "Asha Rao")
    ok("sign-up reply is the same as ever", res.json() == main.CHECK_EMAIL)

    res = client.post("/api/signup", json={"email": "noname@example.com", "password": PASSWORD}, headers=origin)
    ok("a name isn't required by the API", res.status_code == 200 and db.user_by_email("noname@example.com")["name"] == "")
    res = client.post("/api/signup", json={"email": "long@example.com", "password": PASSWORD, "name": "x" * 81}, headers=origin)
    ok("over-long name refused", res.status_code == 422)

    res = client.post("/api/signup", json={"email": "asha@example.com", "password": "another password", "name": "Mallory"}, headers=origin)
    ok("signing up again doesn't change an existing account's name", db.user_by_email("asha@example.com")["name"] == "Asha Rao")

    db.mark_verified(user["id"])
    res = client.post("/api/login", json={"email": "asha@example.com", "password": PASSWORD}, headers=origin)
    ok("login returns the name", res.json()["name"] == "Asha Rao")

    res = client.put("/api/account/name", json={"name": "Asha R"}, headers=origin)
    ok("name can be changed", res.status_code == 200 and res.json()["name"] == "Asha R")
    ok("me returns the new name", client.get("/api/me").json()["account"]["name"] == "Asha R")
    ok("blank name refused", client.put("/api/account/name", json={"name": " \t "}, headers=origin).status_code == 400)
    ok("other sites can't change it", client.put("/api/account/name", json={"name": "X"}, headers={"Origin": "https://evil.example"}).status_code == 403)

    stranger = TestClient(main.app)   # a second browser: no cookies, same running app
    ok("signed out can't change a name", stranger.put("/api/account/name", json={"name": "X"}, headers=origin).status_code == 401)

    # ---------- 404 ----------
    res = client.get("/no/such/page")
    ok("unknown page: a real 404, with the app's page", res.status_code == 404 and "text/html" in res.headers["content-type"] and '<div id="root">' in res.text)
    ok("still has the security headers", "content-security-policy" in {k.lower() for k in res.headers})
    res = client.get("/api/no-such-thing")
    ok("unknown API path stays JSON", res.status_code == 404 and res.headers["content-type"].startswith("application/json"))
    res = client.get("/assets/missing.js")
    ok("missing asset isn't served the page", res.status_code == 404 and "text/html" not in res.headers.get("content-type", ""))
    ok("real pages still 200", client.get("/messages").status_code == 200 and client.get("/privacy").status_code == 200)
    res = client.get("/api/scans/AAAAAAAAAAAAAAAAAAAA")
    ok("API errors keep their message", res.status_code == 404 and "expired" in res.json()["detail"])

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
