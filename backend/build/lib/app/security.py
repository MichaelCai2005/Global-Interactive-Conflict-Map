"""Who may change data through the API.

Reads (GET, HEAD, OPTIONS) are open to everyone. Signing up and in is open too, and a
signed-in person may change their own watchlist, tasks, boards and searches (the routes
check whose rows they touch; see app.auth). Every other write, such as an upload, is open
on a local install with no ADMIN_TOKEN set, needs the token once one is set, and is
refused outright on a public deployment (PUBLIC_MODE=true) without one. Board drafts and
topics can call Claude on the host's key, so a public site must never let strangers
through anonymously.
"""

import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import SIGN_IN_PROMPT, presented_token, session_user
from app.config import get_settings
from app.db import get_db

__all__ = ["READ_METHODS", "UNPUBLISHABLE", "guard_writes", "presented_token"]

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Sources whose events may never reach a public deployment (ACLED's license).
UNPUBLISHABLE = ("acled",)
# Routes anyone may post to, and the ones a signed-in person changes their own data on.
ACCOUNT_ROUTES = frozenset({"/auth/signup", "/auth/login", "/auth/logout"})
PERSONAL_ROUTES = ("/auth/", "/watchlist", "/tasks", "/boards", "/searches")


def _route(request: Request) -> str:
    """The matched route's template, e.g. /ingest/{source}. It doesn't change when the
    API is mounted under a prefix (app.site serves it at /api)."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def _same_site(request: Request) -> None:
    """Refuses a cookie-carrying write sent from another site's page. SameSite=Lax cookies
    already stop most of these; a public site checks the Origin header as well. The sites
    in CORS_ORIGINS, such as the frontend on GitHub Pages, are let through."""
    origin = request.headers.get("origin")
    settings = get_settings()
    if not origin or not settings.public_mode or origin in settings.allowed_origins:
        return
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if urlsplit(origin).netloc != host:
        raise HTTPException(403, "cross-site request refused")


def guard_writes(request: Request, db: Annotated[Session, Depends(get_db)]) -> None:
    """App-wide dependency: lets reads through and checks every other method."""
    if request.method in READ_METHODS:
        return
    settings = get_settings()
    route = _route(request)
    # The startup check keeps ACLED out of a public database; this keeps it from arriving
    # later through an upload, token or not.
    uploading = route.startswith("/ingest/")
    if settings.public_mode and uploading and request.path_params.get("source") in UNPUBLISHABLE:
        raise HTTPException(403, "this source's license forbids a public deployment")
    if route in ACCOUNT_ROUTES:
        _same_site(request)
        return
    personal = route.startswith(PERSONAL_ROUTES)
    if personal and session_user(request, db) is not None:
        _same_site(request)
        return
    if not settings.admin_token:
        if settings.public_mode:
            if personal:
                raise HTTPException(401, SIGN_IN_PROMPT)
            raise HTTPException(403, "this deployment is read-only")
        return
    token = presented_token(request)
    if token is None or not secrets.compare_digest(token.encode(), settings.admin_token.encode()):
        if personal:
            raise HTTPException(401, SIGN_IN_PROMPT, {"WWW-Authenticate": "Bearer"})
        raise HTTPException(
            401, "an admin token is required to change data", {"WWW-Authenticate": "Bearer"}
        )
