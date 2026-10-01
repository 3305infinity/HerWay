"""
Server-side identity for HerWay.

The rule this module exists to enforce: **the server decides who you are.**

Before this existed, every case endpoint took ``user_id`` as an optional query
parameter supplied by the browser. Anyone could read, edit, archive or research
any case by guessing or omitting an id — and every anonymous user shared the
single literal user id ``"anonymous"``, so anonymous case files were pooled
together and visible to each other.

Identity resolution order
-------------------------
1. ``Authorization: Bearer <clerk session token>`` — verified against Clerk's
   JWKS (RS256). The subject becomes the case owner id.
2. An anonymous session cookie (``herway_sid``). HerWay deliberately supports
   anonymous use — a woman may not be able to create an account safely — but
   each anonymous browser still gets its *own* namespace rather than a shared
   one. The id is a signed, opaque random value; it identifies a browser
   session, not a person.

Dev mode
--------
``HERWAY_AUTH_MODE=dev`` additionally honours an ``X-Dev-User-Id`` header so the
stack can be run without a Clerk project. It logs a warning on every use and
refuses to start in that mode when ``HERWAY_ENV=production``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, Response, status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANON_COOKIE_NAME = "herway_sid"
ANON_COOKIE_MAX_AGE = 60 * 60 * 24 * 180  # 180 days

#: Secret used to sign the anonymous session cookie. A random per-process value
#: is used when unset, which logs out anonymous users on restart — acceptable
#: for local development, flagged loudly for production.
_SESSION_SECRET = os.getenv("HERWAY_SESSION_SECRET", "")

CLERK_ISSUER = os.getenv("CLERK_ISSUER", "").rstrip("/")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")
CLERK_AUDIENCE = os.getenv("CLERK_AUDIENCE", "")


def _auth_mode() -> str:
    return os.getenv("HERWAY_AUTH_MODE", "").strip().lower()


def _is_production() -> bool:
    return os.getenv("HERWAY_ENV", "").strip().lower() == "production"


def _session_secret() -> str:
    global _SESSION_SECRET
    if not _SESSION_SECRET:
        if _is_production():
            raise RuntimeError(
                "HERWAY_SESSION_SECRET must be set in production. Anonymous "
                "session cookies cannot be signed without it."
            )
        _SESSION_SECRET = secrets.token_hex(32)
        logger.warning(
            "HERWAY_SESSION_SECRET is not set. Using an ephemeral secret — "
            "anonymous sessions will not survive a restart."
        )
    return _SESSION_SECRET


def clerk_is_configured() -> bool:
    """True when enough Clerk configuration exists to verify a token."""
    return bool(CLERK_JWKS_URL or CLERK_ISSUER)


def _jwks_url() -> Optional[str]:
    if CLERK_JWKS_URL:
        return CLERK_JWKS_URL
    if CLERK_ISSUER:
        return f"{CLERK_ISSUER}/.well-known/jwks.json"
    return None


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    """Who the server believes this request is from."""

    subject: str
    kind: str  # "clerk" | "anonymous"

    @property
    def is_authenticated(self) -> bool:
        return self.kind == "clerk"

    @property
    def owner_id(self) -> str:
        """The value stored on a case's ``user_id`` field."""
        return self.subject


# ---------------------------------------------------------------------------
# Anonymous session cookie
# ---------------------------------------------------------------------------

def _sign(value: str) -> str:
    mac = hmac.new(_session_secret().encode(), value.encode(), hashlib.sha256)
    return mac.hexdigest()[:32]


def _mint_anon_id() -> str:
    raw = secrets.token_urlsafe(24)
    return f"anon_{raw}.{_sign(raw)}"


def _verify_anon_id(value: str) -> Optional[str]:
    """Return the id if its signature checks out, else None."""
    if not value or not value.startswith("anon_") or "." not in value:
        return None
    body, _, signature = value.partition(".")
    raw = body[len("anon_"):]
    try:
        if not hmac.compare_digest(signature, _sign(raw)):
            return None
    except RuntimeError:
        return None
    return value


# ---------------------------------------------------------------------------
# Clerk token verification
# ---------------------------------------------------------------------------

_jwks_cache: Dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


async def _get_jwks() -> Optional[Dict[str, Any]]:
    url = _jwks_url()
    if not url:
        return None

    now = time.time()
    if _jwks_cache["keys"] is not None and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS:
        return _jwks_cache["keys"]

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            keys = resp.json()
        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = now
        return keys
    except Exception as exc:
        logger.error("Auth: could not fetch Clerk JWKS from %s: %s", url, exc)
        # Serve a stale copy rather than locking everyone out during a blip.
        return _jwks_cache["keys"]


async def _verify_clerk_token(token: str) -> Optional[str]:
    """Verify a Clerk session token and return its subject, or None."""
    jwks = await _get_jwks()
    if not jwks:
        return None

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return None

    kid = header.get("kid")
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key_data is None:
        # Key rotation — refresh once before giving up.
        _jwks_cache["fetched_at"] = 0.0
        jwks = await _get_jwks()
        key_data = next((k for k in (jwks or {}).get("keys", []) if k.get("kid") == kid), None)
    if key_data is None:
        logger.warning("Auth: no JWKS key matching kid=%s", kid)
        return None

    try:
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        options = {"verify_aud": bool(CLERK_AUDIENCE)}
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=CLERK_AUDIENCE or None,
            issuer=CLERK_ISSUER or None,
            options=options,
            leeway=30,
        )
    except jwt.ExpiredSignatureError:
        logger.info("Auth: rejected expired Clerk token")
        return None
    except jwt.PyJWTError as exc:
        logger.info("Auth: rejected Clerk token (%s)", exc.__class__.__name__)
        return None

    subject = claims.get("sub")
    if not subject:
        return None
    return str(subject)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_identity(request: Request, response: Response) -> Identity:
    """Resolve the caller's identity. Never trusts a client-supplied user id."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            subject = await _verify_clerk_token(token)
            if subject:
                return Identity(subject=subject, kind="clerk")
            # A token was presented and it did not verify. Do not quietly fall
            # back to an anonymous session — that would mask a broken or
            # tampered login.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session has expired or is not valid. Please sign in again.",
            )

    if _auth_mode() == "dev":
        if _is_production():
            raise RuntimeError(
                "HERWAY_AUTH_MODE=dev cannot be used with HERWAY_ENV=production."
            )
        dev_user = request.headers.get("x-dev-user-id", "").strip()
        if dev_user:
            logger.warning(
                "Auth: accepting X-Dev-User-Id=%s because HERWAY_AUTH_MODE=dev", dev_user
            )
            return Identity(subject=f"dev_{dev_user}", kind="clerk")

    # Anonymous: give this browser its own isolated namespace.
    existing = _verify_anon_id(request.cookies.get(ANON_COOKIE_NAME, ""))
    if existing:
        return Identity(subject=existing, kind="anonymous")

    new_id = _mint_anon_id()
    response.set_cookie(
        ANON_COOKIE_NAME,
        new_id,
        max_age=ANON_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_production(),
        path="/",
    )
    return Identity(subject=new_id, kind="anonymous")


async def require_authenticated(
    identity: Identity = Depends(get_identity),
) -> Identity:
    """Require a signed-in Clerk user (used for account-scoped operations)."""
    if not identity.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please sign in to continue.",
        )
    return identity


def assert_case_owner(case_doc: Dict[str, Any], identity: Identity) -> None:
    """Raise 403 unless ``identity`` owns ``case_doc``.

    Legacy documents created before server-side identity existed carry the
    shared literal owner ``"anonymous"``. Those are treated as *inaccessible*
    rather than public — the alternative is letting any visitor read case notes
    written by an abuse survivor.
    """
    owner = case_doc.get("user_id")
    if owner and owner == identity.owner_id:
        return

    logger.warning(
        "Auth: denied access to case %s for subject kind=%s",
        case_doc.get("_id"),
        identity.kind,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This case belongs to a different account or session.",
    )


def owner_filter(identity: Identity) -> Dict[str, Any]:
    """A Mongo filter fragment restricting a query to this caller's documents."""
    return {"user_id": identity.owner_id}


def startup_auth_check() -> None:
    """Fail fast on an unsafe production configuration."""
    if not _is_production():
        if not clerk_is_configured():
            logger.warning(
                "Auth: Clerk is not configured. Signed-in identity is unavailable; "
                "requests will be treated as anonymous browser sessions."
            )
        return

    problems = []
    if not clerk_is_configured():
        problems.append("CLERK_ISSUER or CLERK_JWKS_URL must be set")
    if not os.getenv("HERWAY_SESSION_SECRET"):
        problems.append("HERWAY_SESSION_SECRET must be set")
    if _auth_mode() == "dev":
        problems.append("HERWAY_AUTH_MODE must not be 'dev'")

    if problems:
        raise RuntimeError(
            "Refusing to start in production with an unsafe auth configuration: "
            + "; ".join(problems)
        )
