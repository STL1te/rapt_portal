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


def _post(data: dict) -> dict:
    resp = httpx.post(TOKEN_URL, data={"client_id": OAUTH_CLIENT_ID, **data}, timeout=30)
    if resp.is_error:
        # the body carries the real reason (invalid_grant, expired code, ...)
        raise RuntimeError(f"RAPT auth {resp.status_code}: {resp.text or '(empty body)'}")
    return resp.json()


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
        refresh = _load_refresh()
        if not refresh:
            raise RuntimeError(NOT_CONNECTED)
        try:
            return _store({"grant_type": "refresh_token", "refresh_token": refresh})
        except RuntimeError:
            # a rejected refresh token stays rejected — drop it so the UI says
            # "not connected" instead of failing every sync with the same error
            _save_refresh("")
            _access = ""
            raise


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
    print("rapt_auth OK")


if __name__ == "__main__":
    demo()
