"""Google sign-in state is shared by every API process (kept in Redis) and can be used once.

The API runs several processes, so the callback from Google often reaches a different process than the
one that started the sign-in. State kept in one process's memory made those sign-ins fail.
"""
import asyncio
import os

os.environ["REDIS_URL"] = "fake://"
os.environ["GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"
import google_auth  # noqa: E402
import store  # noqa: E402

results = []


def ok(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


state, url = google_auth.start()
ok("the sign-in is stored in Redis, where every process can see it",
   any(k.startswith("oauth:") for k in store.sync_client().keys("*")))
ok("Redis holds a hash of the state, not the state itself", not any(state in k for k in store.sync_client().keys("*")))
ok("it expires on its own", all(0 < store.sync_client().ttl(k) <= google_auth.STATE_SECONDS for k in store.sync_client().keys("oauth:*")))
ok("the Google URL carries the state", f"state={state}" in url)


async def finish_without_google(s):
    # Stop at the token request: only the state check matters here.
    real = google_auth.httpx.AsyncClient
    google_auth.httpx.AsyncClient = None   # any use raises TypeError, after the state check
    try:
        await google_auth.finish(s, "code")
    except google_auth.GoogleError as exc:
        return str(exc)
    except TypeError:
        return "state accepted"
    finally:
        google_auth.httpx.AsyncClient = real

ok("a known state is accepted", asyncio.run(finish_without_google(state)) == "state accepted")
ok("the same state can't be used twice", asyncio.run(finish_without_google(state)) == "unknown or expired state")
ok("an unknown state is refused", asyncio.run(finish_without_google("made-up")) == "unknown or expired state")
print(f"\n{sum(results)}/{len(results)} passed")
