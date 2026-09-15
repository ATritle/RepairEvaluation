"""Windows AD sign-in, using the shared IFP `auth-middleware` package.

The middleware (mrwuss/auth-middleware) answers *who is this*: it validates
domain credentials with LogonUser via HTTP Basic, then issues a signed
session cookie. Browsers show their native login prompt the first time.

This module adds what the package deliberately leaves out:

- config from our .env (Settings) instead of raw environment variables
- an optional AD **group gate** (AUTH_GROUP): authenticated users who are not
  members get 403. Membership comes from the domain controller through
  pywin32 and is cached.
- display names for `saved_by` / `uploaded_by`
- /api/me, /logout and /health

Everything here runs only on a domain-joined Windows host, which is also the
only place LogonUser works.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import DATA
from .settings import get_settings

log = logging.getLogger("repaireval.auth")

EXEMPT_PATHS = ["/health", "/static", "/assets"]
_CACHE_TTL = 1800  # seconds; group membership and display names


def _cookie_secret() -> str:
    """Use AUTH_COOKIE_SECRET; if blank, generate once and keep it in data/ so
    sessions survive restarts (a fresh secret on every boot logs everyone out)."""
    st = get_settings()
    if st.auth_cookie_secret:
        return st.auth_cookie_secret
    p = DATA / "auth_cookie_secret"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    DATA.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    p.write_text(value, encoding="utf-8")
    log.warning("AUTH_COOKIE_SECRET not set; generated one at %s", p)
    return value


# --------------------------------------------------------------------------
# AD lookups (pywin32), cached
# --------------------------------------------------------------------------
_group_cache: dict[str, tuple[float, bool]] = {}
_name_cache: dict[str, tuple[float, str]] = {}
_dc_cache: dict[str, str] = {}


def _dc() -> str:
    """\\\\dcname for the configured domain (NetGetDCName), cached."""
    st = get_settings()
    if "dc" not in _dc_cache:
        import win32net  # type: ignore

        _dc_cache["dc"] = win32net.NetGetDCName(None, st.auth_domain or None)
    return _dc_cache["dc"]


def user_groups(login: str) -> set[str]:
    """Global AD groups the account belongs to (lower-cased). Nested membership
    is not expanded; put users in the gate group directly."""
    import win32net  # type: ignore

    groups, _total, _resume = win32net.NetUserGetGroups(_dc(), login)
    return {g[0].lower() for g in groups}


def in_group(login: str, group: str) -> bool:
    now = time.time()
    key = f"{login}|{group}".lower()
    hit = _group_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    try:
        ok = group.lower() in user_groups(login)
    except Exception as exc:  # DC unreachable, unknown user, ...
        log.warning("group lookup failed for %s: %s", login, exc)
        ok = False
    _group_cache[key] = (now + _CACHE_TTL, ok)
    return ok


def display_name(login: str) -> str:
    now = time.time()
    hit = _name_cache.get(login)
    if hit and hit[0] > now:
        return hit[1]
    name = login
    try:
        import win32net  # type: ignore

        info = win32net.NetUserGetInfo(_dc(), login, 2)
        name = (info.get("full_name") or "").strip() or login
    except Exception as exc:
        log.debug("display name lookup failed for %s: %s", login, exc)
    _name_cache[login] = (now + _CACHE_TTL, name)
    return name


# --------------------------------------------------------------------------
# Identity helpers used by routes
# --------------------------------------------------------------------------
def current_login(request: Request) -> Optional[str]:
    """Lower-case sAMAccountName of the signed-in user, or None (exempt path / auth off)."""
    return getattr(request.state, "user", None)


def identity_label(request: Request) -> Optional[str]:
    """'jsmith (John Smith)' for saved_by / uploaded_by; None if nobody is signed in."""
    login = current_login(request)
    if not login:
        return None
    if not get_settings().auth_enabled:
        return login  # dev user, no AD to ask
    name = display_name(login)
    return f"{login} ({name})" if name and name.lower() != login.lower() else login


# --------------------------------------------------------------------------
# Group gate
# --------------------------------------------------------------------------
class GroupGateMiddleware(BaseHTTPMiddleware):
    """After WindowsAuthMiddleware: refuse authenticated users outside AUTH_GROUP."""

    async def dispatch(self, request: Request, call_next):
        st = get_settings()
        login = getattr(request.state, "user", None)
        if st.auth_enabled and st.auth_group and login and not in_group(login, st.auth_group):
            log.info("refused %s: not in group %s", login, st.auth_group)
            msg = f"{login} is signed in but is not a member of the '{st.auth_group}' group required for this app."
            if "text/html" in request.headers.get("accept", ""):
                return Response(_forbidden_html(msg), status_code=403, media_type="text/html")
            return JSONResponse({"detail": msg}, status_code=403)
        return await call_next(request)


def _forbidden_html(msg: str) -> str:
    return f"""<!doctype html><meta charset="utf-8"><title>Not authorised</title>
<body style="font-family:Segoe UI,Arial;background:#171717;color:#f2f2f2;padding:40px">
<h2 style="color:#ff7a00">Not authorised</h2><p>{msg}</p>
<p style="color:#b8b8b8">Ask IT to add you to the group, then close and reopen your browser.</p></body>"""


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------
def install(app: FastAPI) -> None:
    """Add the auth stack and its routes. Call once, after other middleware."""
    from auth_middleware import WindowsAuthMiddleware, get_auth_middleware

    st = get_settings()
    if not st.auth_enabled:
        # get_current_user's dev fallback is unlocked only by this env var.
        os.environ["AUTH_DISABLED"] = "1"
        log.warning("AUTH_ENABLED=false: every request is '%s'. Dev only.", st.auth_dev_user)

    # Middleware runs in reverse order of add_middleware: add the gate first so
    # it executes after (inside) the auth middleware.
    app.add_middleware(GroupGateMiddleware)
    app.add_middleware(
        WindowsAuthMiddleware,
        auth_disabled=not st.auth_enabled,
        dev_user=st.auth_dev_user,
        auth_domain=st.auth_domain,
        cookie_name=st.auth_cookie_name,
        cookie_secret=_cookie_secret() if st.auth_enabled else None,
        session_ttl=st.auth_session_ttl,
        exempt_paths=EXEMPT_PATHS,
        cookie_secure=st.auth_cookie_secure,
    )

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/me")
    async def me(request: Request) -> dict:
        login = current_login(request)
        return {
            "user": login,
            "name": display_name(login) if (login and st.auth_enabled) else login,
            "auth_enabled": st.auth_enabled,
            "group": st.auth_group or None,
        }

    @app.get("/logout", include_in_schema=False)
    async def logout(request: Request) -> Response:
        """Clear the session cookie. Note: a browser that authenticated with Basic
        keeps those credentials until it is fully closed, so it may sign straight
        back in; the page says so."""
        resp = Response(
            """<!doctype html><meta charset="utf-8"><title>Signed out</title>
<body style="font-family:Segoe UI,Arial;background:#171717;color:#f2f2f2;padding:40px">
<h2>Signed out</h2><p>Your session was cleared. Close every window of this browser to finish
signing out — browsers remember Windows credentials until they are fully closed.</p>
<p><a style="color:#ff7a00" href="/">Back to Repair Evaluation</a></p></body>""",
            media_type="text/html",
        )
        try:
            get_auth_middleware(request).clear_session_cookie(resp, request)
        except Exception as exc:
            log.debug("logout: no middleware on request (%s)", exc)
        return resp
