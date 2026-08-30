"""OAuth login to RAPT (authorization code + PKCE), replacing hand-pasted tokens.

id.rapt.io only accepts https://app.rapt.io/callback as a redirect for its public
`rapt-web` client, so the browser lands back on RAPT's own SPA instead of on us:
the user copies that callback URL here once, and from then on the stored refresh
token keeps both the public API and the portal-only endpoints signed in.
"""

import base64
import hashlib
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from core.config import (
    APP_SECRET,
    AUTHORIZE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPE,
    TOKEN_URL,
)
from core.db import AppSetting, SessionLocal

logger = logging.getLogger(__name__)

_REFRESH_KEY = "rapt_refresh_token"
NOT_CONNECTED = "RAPT не подключён — войдите через RAPT на странице «Системные синки»"

_pending: dict[str, str] = {}  # state -> PKCE verifier, until the code comes back
_lock = threading.Lock()
_access: str = ""
_expiry: float = 0.0


def _cipher() -> Fernet:
    """Fernet key derived from APP_SECRET — the refresh token is a live credential and
    must not sit in the database in the clear."""
    if not APP_SECRET:
        raise RuntimeError("Задайте APP_SECRET в backend/.env — им шифруется токен RAPT")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(APP_SECRET.encode()).digest()))


def _load_refresh() -> str:
    with SessionLocal() as db:
        row = db.get(AppSetting, _REFRESH_KEY)
    if not row or not row.value:
        return ""
    try:
        return _cipher().decrypt(row.value.encode()).decode()
    except InvalidToken:
        # APP_SECRET changed (or the row was written under another one) — the token is
        # unreadable, so the only honest answer is "not connected".
        logger.warning("stored RAPT token does not decrypt with APP_SECRET — log in again")
        return ""


def _save_refresh(value: str) -> None:
    encrypted = _cipher().encrypt(value.encode()).decode() if value else ""
    with SessionLocal() as db:
        db.merge(AppSetting(key=_REFRESH_KEY, value=encrypted))
        db.commit()


def token_payload(resp: httpx.Response) -> dict:
    """A token-endpoint reply that actually carries a token.

    Both the error body (invalid_grant, expired code, ...) and a 200 that simply has no
    access_token in it must name themselves: read straight through, the second one shows
    up in the job log as a bare KeyError `'access_token'` and says nothing at all.
    """
    if resp.is_error:
        raise RuntimeError(f"RAPT auth {resp.status_code}: {resp.text or '(empty body)'}")
    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError(f"RAPT auth {resp.status_code} без access_token: {resp.text[:300]}")
    return data


def _post(data: dict) -> dict:
    return token_payload(
        httpx.post(TOKEN_URL, data={"client_id": OAUTH_CLIENT_ID, **data}, timeout=30)
    )


def _store(data: dict) -> str:
    """Cache the access token and persist the (possibly rotated) refresh token."""
    global _access, _expiry
    if data.get("refresh_token"):
        _save_refresh(data["refresh_token"])
    _access = data["access_token"]
    _expiry = time.time() + data.get("expires_in", 3600)
    return _access


def login_url() -> str:
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(16)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    _pending[state] = verifier
    return f"{AUTHORIZE_URL}?" + urlencode(
        {
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "state": state,
            "nonce": secrets.token_urlsafe(16),
            "code_challenge": challenge.decode(),
            "code_challenge_method": "S256",
        }
    )


def parse_code(pasted: str) -> tuple[str, str]:
    """Accept the whole callback URL or a bare code; return (code, state)."""
    pasted = pasted.strip()
    query = parse_qs(urlparse(pasted).query)
    if query.get("error"):
        raise ValueError(f"RAPT вернул ошибку: {query['error'][0]}")
    if query.get("code"):
        return query["code"][0], (query.get("state") or [""])[0]
    if not pasted or "?" in pasted or "/" in pasted:
        raise ValueError("Не нашёл code — вставьте адрес страницы callback целиком")
    return pasted, ""


def complete(pasted: str) -> None:
    """Exchange the pasted authorization code for tokens."""
    code, state = parse_code(pasted)
    _cipher()  # fail before burning the one-shot code if APP_SECRET is missing
    verifier = _pending.get(state)
    if verifier is None:
        if len(_pending) != 1:
            raise ValueError("Вход не начат или уже устарел — нажмите «Войти через RAPT» заново")
        verifier = next(iter(_pending.values()))
    with _lock:
        _store(
            _post(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": OAUTH_REDIRECT_URI,
                    "code_verifier": verifier,
                }
            )
        )
    _pending.clear()


def is_connected() -> bool:
    # a live access token answers without a DB round trip — get_token() asks per API call
    if _access and time.time() < _expiry - 60:
        return True
    return bool(_load_refresh())


def access_token() -> str:
    """A valid RAPT bearer token, refreshed 60s before it expires."""
    global _access
    with _lock:
        if _access and time.time() < _expiry - 60:
            return _access
        for attempt in (1, 2):
            refresh = _load_refresh()
            if not refresh:
                raise RuntimeError(NOT_CONNECTED)
            try:
                return _store(_post({"grant_type": "refresh_token", "refresh_token": refresh}))
            except RuntimeError:
                # RAPT rotates the refresh token on every use, so another instance on this
                # database may have just spent ours. Re-read the row once and use what it
                # stored; a token that is genuinely dead fails again and says so.
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")


def _legacy_token() -> str:
    """Pre-OAuth escape hatch: PORTAL_TOKEN / .portal_token, still used by scripts."""
    tok = os.environ.get("PORTAL_TOKEN", "")
    if not tok and Path(".portal_token").exists():
        tok = Path(".portal_token").read_text(encoding="utf-8")
    return tok.removeprefix("Bearer ").strip()


def portal_token() -> str:
    """Bearer token for the portal-only endpoints."""
    if is_connected():
        return access_token()
    tok = _legacy_token()
    if not tok:
        raise RuntimeError(NOT_CONNECTED)
    return tok


def demo() -> None:
    """Self-check: pasted-value parsing and the login URL."""
    assert parse_code("https://app.rapt.io/callback?code=abc&state=xy") == ("abc", "xy")
    assert parse_code("  abc123  ") == ("abc123", "")
    for bad in ["", "https://app.rapt.io/callback", "https://app.rapt.io/callback?error=denied"]:
        try:
            parse_code(bad)
            raise AssertionError(f"expected a rejection for {bad!r}")
        except ValueError:
            pass
    url = login_url()
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"], q
    assert q["state"][0] in _pending
    verifier = _pending[q["state"][0]]
    expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert q["code_challenge"] == [expect.decode()]
    _pending.clear()

    # The refresh path must go through the token endpoint. Handing the request dict
    # straight to _store() shipped once and failed every sync with KeyError
    # 'access_token' and no request in sight.
    global _access, _expiry
    calls = []

    class _FakeResponse:
        is_error = False
        status_code = 200
        text = ""

        def json(self) -> dict:
            return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

    real_post, real_load, real_save = httpx.post, _load_refresh, _save_refresh
    try:
        httpx.post = lambda url, **kw: (calls.append(kw["data"]), _FakeResponse())[1]
        globals()["_load_refresh"] = lambda: "stored-refresh"
        globals()["_save_refresh"] = lambda value: calls.append(("saved", value))
        _access, _expiry = "", 0.0
        assert access_token() == "at"
        assert calls[0]["grant_type"] == "refresh_token", calls
        assert calls[0]["refresh_token"] == "stored-refresh", calls
        assert ("saved", "rt") in calls, "rotated refresh token was not stored"
    finally:
        httpx.post, _access, _expiry = real_post, "", 0.0
        globals()["_load_refresh"], globals()["_save_refresh"] = real_load, real_save
    print("rapt_auth OK")


if __name__ == "__main__":
    demo()
