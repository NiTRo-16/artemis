"""Sign in with Google: OpenID Connect authorization code flow with PKCE.

Only the `openid email` scopes are requested, so Google shares the account's ID and email address,
nothing else. Enabled when GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlencode

import httpx

from mail import APP_URL

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
ENABLED = bool(CLIENT_ID and CLIENT_SECRET)
REDIRECT_URI = f"{APP_URL}/api/auth/google/callback"   # register exactly this in the Google Cloud console
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
STATE_SECONDS = 600      # time allowed on Google's sign-in screen
MAX_PENDING = 10_000     # sign-ins in progress kept in memory; the oldest are dropped first

# state -> (expires at, PKCE verifier, nonce). In memory: a restart only cancels sign-ins in progress.
_pending: OrderedDict[str, tuple[float, str, str]] = OrderedDict()


class GoogleError(Exception):
    """Sign-in didn't complete; the reason is for the server log only."""


def config_problem() -> str | None:
    if bool(CLIENT_ID) != bool(CLIENT_SECRET):
        return "set both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or neither"
    return None


def start() -> tuple[str, str]:
    """Begin a sign-in: (state, for the browser cookie; Google URL to send the browser to)."""
    now = time.monotonic()
    while _pending and (len(_pending) >= MAX_PENDING or next(iter(_pending.values()))[0] < now):
        _pending.popitem(last=False)
    state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(64), secrets.token_urlsafe(16)
    _pending[state] = (now + STATE_SECONDS, verifier, nonce)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return state, f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _claims(id_token: str) -> dict:
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, binascii.Error) as exc:
        raise GoogleError(f"unreadable ID token: {exc}")


async def finish(state: str, code: str) -> tuple[str, str]:
    """Complete a sign-in from Google's redirect: returns (Google account ID, verified email address)."""
    entry = _pending.pop(state, None)
    if entry is None or entry[0] < time.monotonic():
        raise GoogleError("unknown or expired state")
    _, verifier, nonce = entry
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(TOKEN_ENDPOINT, data={
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            })
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleError(f"token request failed: {exc}")
    if resp.status_code != 200 or not isinstance(data, dict) or not isinstance(data.get("id_token"), str):
        raise GoogleError(f"token endpoint answered {resp.status_code}")

    # The ID token came straight from Google's token endpoint over verified TLS, in exchange for our
    # client secret, so its signature doesn't need checking (OpenID Connect Core 3.1.3.7). The claims
    # are still checked: it must be for this app, current, from this sign-in, with a verified email.
    claims = _claims(data["id_token"])
    email = claims.get("email")
    if claims.get("iss") not in ISSUERS:
        raise GoogleError("wrong issuer")
    if claims.get("aud") != CLIENT_ID:
        raise GoogleError("token is for another app")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < time.time():
        raise GoogleError("token expired")
    if not secrets.compare_digest(str(claims.get("nonce", "")).encode(), nonce.encode()):
        raise GoogleError("nonce mismatch")
    if claims.get("email_verified") is not True or not isinstance(email, str) or not email or len(email) > 254:
        raise GoogleError("email missing or not verified by Google")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise GoogleError("no account ID")
    return claims["sub"], email.strip().lower()
