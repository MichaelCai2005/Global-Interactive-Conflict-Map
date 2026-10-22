"""Who may change data through the API.

Reads (GET, HEAD, OPTIONS) are open to everyone. Writes (uploads, boards, the watchlist
and tasks) are open on a local install with no ADMIN_TOKEN set, need the token once one
is set, and are refused outright on a public deployment (PUBLIC_MODE=true) without one.
Board drafts and topics can call Claude on the host's key, so a public site must never
let strangers through.
"""

import secrets

from fastapi import HTTPException, Request

from app.config import get_settings

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Sources whose events may never reach a public deployment (ACLED's license).
UNPUBLISHABLE = ("acled",)


def presented_token(request: Request) -> str | None:
    """The token from `Authorization: Bearer <token>` or `X-Admin-Token: <token>`."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.headers.get("x-admin-token") or None


def guard_writes(request: Request) -> None:
    """App-wide dependency: lets reads through and checks every other method."""
    if request.method in READ_METHODS:
        return
    settings = get_settings()
    # The startup check keeps ACLED out of a public database; this keeps it from arriving
    # later through an upload, token or not.
    uploading = request.url.path.startswith("/ingest/")
    if settings.public_mode and uploading and request.path_params.get("source") in UNPUBLISHABLE:
        raise HTTPException(403, "this source's license forbids a public deployment")
    if not settings.admin_token:
        if settings.public_mode:
            raise HTTPException(403, "this deployment is read-only")
        return
    token = presented_token(request)
    if token is None or not secrets.compare_digest(token.encode(), settings.admin_token.encode()):
        raise HTTPException(
            401, "an admin token is required to change data", {"WWW-Authenticate": "Bearer"}
        )
