"""Accounts: signing up and in, and whose data each request works on.

People sign up with an email and a password and keep their own watchlist, tasks, boards
and saved searches. Passwords are hashed with scrypt from the standard library. A sign-in
is a random token in an httpOnly cookie, and the database keeps only the token's SHA-256,
so a leaked table can't be replayed. A frontend on another site (GitHub Pages calling the
API on Render) can't rely on that cookie, because browsers block cookies across sites, so
signing in also returns the token and the API accepts it as `Authorization: Bearer`.

Each request that touches personal data works for a Workspace:

- a signed-in person works on their own rows;
- the admin token, or a local install with no ADMIN_TOKEN (how the app ran before
  accounts), works on the shared workspace, which is the rows with no owner;
- anyone else is asked to sign in.

Shared boards double as the public site's showcase: anyone may read them.
"""

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession

COOKIE = "cm_session"
SIGN_IN_PROMPT = "Sign in to keep your own watchlist, tasks, boards and searches"

# scrypt at N=2^15, r=8 takes 32 MB and about 50 ms per hash: slow for anyone guessing,
# light enough for a small host. The parameters are stored with each hash, so they can
# be raised later without locking anyone out.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join(
        ["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64(salt), _b64(digest)]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=4 * 128 * r * n, dklen=32
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# Hashed when an email isn't found, so a wrong email takes as long as a wrong password and
# the timing doesn't reveal who has an account.
_DECOY_HASH = hash_password(secrets.token_urlsafe(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Throttle:
    """Counts attempts per client address in a sliding window. One process keeps its own
    counts, which is enough to slow down guessing against a single small API instance."""

    def __init__(self, limit: int, seconds: int, message: str):
        self.limit, self.seconds, self.message = limit, seconds, message
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        with self._lock:
            hits = self._recent(key)
            if len(hits) >= self.limit:
                retry = int(hits[0] + self.seconds - time.monotonic()) + 1
                raise HTTPException(429, self.message, {"Retry-After": str(retry)})

    def hit(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _recent(self, key: str) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= time.monotonic() - self.seconds:
            hits.popleft()
        return hits


failed_logins = Throttle(10, 15 * 60, "Too many failed sign-ins; try again in a few minutes")
signups = Throttle(5, 60 * 60, "Too many new accounts from this address; try again later")


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# --- Who is asking --------------------------------------------------------------------


@dataclass(frozen=True)
class Workspace:
    """Whose rows a request works on: a person's (user_id) or the shared ones (None)."""

    user_id: int | None

    def where(self, column: Any) -> Any:
        """A filter on an owner column for this workspace's rows."""
        return column.is_(None) if self.user_id is None else column == self.user_id

    def owns(self, row: Any) -> bool:
        return row.user_id == self.user_id


def presented_token(request: Request) -> str | None:
    """The token from `Authorization: Bearer <token>` or `X-Admin-Token: <token>`."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.headers.get("x-admin-token") or None


def has_admin_token(request: Request) -> bool:
    expected = get_settings().admin_token
    token = presented_token(request)
    return bool(expected and token) and secrets.compare_digest(token.encode(), expected.encode())


def open_install() -> bool:
    """A local install with no admin token: anyone who can reach it is its owner."""
    settings = get_settings()
    return not settings.public_mode and not settings.admin_token


_UNKNOWN = object()


def session_token(request: Request) -> str | None:
    """The sign-in token from the cookie, or from the Authorization header for a frontend
    on another site. An admin token in the header matches no sign-in, so it falls through
    to has_admin_token."""
    return request.cookies.get(COOKIE) or presented_token(request)


def session_user(request: Request, db: Session) -> User | None:
    """The person signed in on this request, if the sign-in is still good."""
    cached = getattr(request.state, "user", _UNKNOWN)
    if cached is not _UNKNOWN:
        return cached
    user = None
    if token := session_token(request):
        row = db.get(UserSession, _token_hash(token))
        if row is not None and row.expires_at > datetime.now(UTC):
            user = row.user
    request.state.user = user
    return user


def get_viewer(request: Request, db: Annotated[Session, Depends(get_db)]) -> Workspace | None:
    """Whose workspace this request may see; None for an anonymous visitor."""
    if user := session_user(request, db):
        return Workspace(user.id)
    if has_admin_token(request) or open_install():
        return Workspace(None)
    return None


def require_owner(viewer: Annotated[Workspace | None, Depends(get_viewer)]) -> Workspace:
    if viewer is None:
        raise HTTPException(401, SIGN_IN_PROMPT)
    return viewer


Viewer = Annotated[Workspace | None, Depends(get_viewer)]
Owner = Annotated[Workspace, Depends(require_owner)]
Db = Annotated[Session, Depends(get_db)]


# --- Schemas --------------------------------------------------------------------------


class SignUpIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=8, max_length=256)
    display_name: str = Field("", max_length=100)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL.match(value):
            raise ValueError("enter a valid email address")
        return value


class SignInIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut | None
    # "personal": signed in. "shared": the shared workspace (a local install or the admin
    # token). None: anonymous on a public site, who must sign in to save anything.
    workspace: Literal["personal", "shared"] | None
    signups_open: bool


class SignedIn(MeOut):
    # The sign-in token, for a frontend on another site to send back as
    # `Authorization: Bearer`; the same token is also set as the cookie.
    token: str


class ProfilePatch(BaseModel):
    display_name: str | None = Field(None, max_length=100)
    new_password: str | None = Field(None, min_length=8, max_length=256)
    current_password: str | None = Field(None, max_length=256)


class PasswordIn(BaseModel):
    password: str = Field(..., max_length=256)


# --- Routes ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["accounts"])


def _me(request: Request, db: Session) -> MeOut:
    viewer = get_viewer(request, db)
    user = session_user(request, db)
    return MeOut(
        user=UserOut.model_validate(user) if user else None,
        workspace=None if viewer is None else "personal" if user else "shared",
        signups_open=get_settings().signups_open,
    )


def _start_session(request: Request, response: Response, db: Session, user: User) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    # Drop this person's expired sign-ins while here, so the table doesn't grow forever.
    db.execute(
        delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at <= now)
    )
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=now + timedelta(days=settings.session_days),
            user_agent=request.headers.get("user-agent", "")[:300],
        )
    )
    user.last_login_at = now
    db.commit()
    secure = settings.public_mode if settings.secure_cookies is None else settings.secure_cookies
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    request.state.user = user
    request.state.session_token = token


def _signed_in_as(request: Request, db: Session) -> SignedIn:
    return SignedIn(**_me(request, db).model_dump(), token=request.state.session_token)


@router.get("/me", response_model=MeOut)
def me(request: Request, db: Db):
    return _me(request, db)


@router.post("/signup", response_model=SignedIn, status_code=201)
def sign_up(body: SignUpIn, request: Request, response: Response, db: Db):
    if not get_settings().signups_open:
        raise HTTPException(403, "This site isn't taking new accounts")
    signups.check(_client(request))
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise HTTPException(409, "An account with this email already exists; sign in instead")
    signups.hit(_client(request))
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
    )
    db.add(user)
    db.flush()
    _start_session(request, response, db, user)
    return _signed_in_as(request, db)


@router.post("/login", response_model=SignedIn)
def sign_in(body: SignInIn, request: Request, response: Response, db: Db):
    failed_logins.check(_client(request))
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not verify_password(body.password, user.password_hash if user else _DECOY_HASH) or not user:
        failed_logins.hit(_client(request))
        raise HTTPException(401, "Wrong email or password")
    _start_session(request, response, db, user)
    return _signed_in_as(request, db)


@router.post("/logout", status_code=204)
def sign_out(request: Request, db: Db):
    if token := session_token(request):
        db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
        db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


def _signed_in(request: Request, db: Session) -> User:
    user = session_user(request, db)
    if user is None:
        raise HTTPException(401, "Sign in first")
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: ProfilePatch, request: Request, db: Db):
    """Change the display name, or the password (which needs the current one and signs
    out every other browser)."""
    user = _signed_in(request, db)
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.new_password is not None:
        if not verify_password(body.current_password or "", user.password_hash):
            raise HTTPException(403, "The current password is wrong")
        user.password_hash = hash_password(body.new_password)
        keep = _token_hash(session_token(request) or "")
        db.execute(
            delete(UserSession).where(
                UserSession.user_id == user.id, UserSession.token_hash != keep
            )
        )
    db.commit()
    return user


@router.delete("/me", status_code=204)
def delete_me(body: PasswordIn, request: Request, db: Db):
    """Delete the account and everything in it: watchlist, tasks, boards, searches."""
    user = _signed_in(request, db)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "The password is wrong")
    # The owner columns cascade in the database, boards taking their nodes with them.
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response
