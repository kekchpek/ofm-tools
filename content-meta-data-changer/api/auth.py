"""Google OAuth and cookie session authentication."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import Cookie, Depends, HTTPException, Request

from api.database import (
    UserRecord,
    consume_oauth_state,
    create_auth_session,
    create_oauth_state,
    delete_auth_session,
    get_user_for_auth_token,
    register_upload_session,
    upload_session_owner,
    upsert_google_user,
)
from core.models import AuthConfigDTO, UserDTO

SESSION_COOKIE_NAME = "cmc_session"
CLIENT_COOKIE_NAME = "cmc_client"
CLIENT_COOKIE_MAX_AGE = 30 * 24 * 3600
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def auth_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def auth_session_ttl_hours() -> int:
    return int(os.environ.get("AUTH_SESSION_TTL_HOURS", "168"))


def frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def google_redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_REDIRECT_URI",
        "http://localhost:5173/api/v1/auth/google/callback",
    )


def auth_config() -> AuthConfigDTO:
    return AuthConfigDTO(
        enabled=auth_enabled(),
        login_url="/api/v1/auth/google" if auth_enabled() else None,
        redirect_uri=google_redirect_uri() if auth_enabled() else None,
    )


def user_to_dto(user: UserRecord) -> UserDTO:
    return UserDTO(
        id=user.id,
        email=user.email,
        name=user.name,
        picture_url=user.picture_url,
    )


def _cookie_secure() -> bool:
    return os.environ.get("AUTH_COOKIE_SECURE", "0") == "1"


def _cookie_samesite() -> str:
    """Use ``none`` when the frontend and API are on different origins (e.g. Cloudflare + Railway)."""
    value = os.environ.get("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    if value in {"lax", "strict", "none"}:
        return value
    return "lax"


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        max_age=auth_session_ttl_hours() * 3600,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
    )


def new_client_id() -> str:
    return secrets.token_urlsafe(32)


def set_client_cookie(response, client_id: str) -> None:
    response.set_cookie(
        key=CLIENT_COOKIE_NAME,
        value=client_id,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        max_age=CLIENT_COOKIE_MAX_AGE,
        path="/",
    )


def get_client_id_optional(
    cmc_client: str | None = Cookie(default=None),
) -> str | None:
    """Anonymous browser identity used to scope upload sessions when OAuth is off."""
    return cmc_client or None


def get_current_user_optional(
    cmc_session: str | None = Cookie(default=None),
) -> UserRecord | None:
    if not cmc_session:
        return None
    return get_user_for_auth_token(cmc_session)


def require_user(
    user: UserRecord | None = Depends(get_current_user_optional),
) -> UserRecord:
    if not auth_enabled():
        raise HTTPException(
            status_code=503,
            detail={"error": "Authentication is not configured.", "code": "auth_not_configured"},
        )
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "Sign in required.", "code": "unauthorized"},
        )
    return user


def require_user_or_anonymous(
    user: UserRecord | None = Depends(get_current_user_optional),
) -> UserRecord | None:
    if auth_enabled() and user is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "Sign in required.", "code": "unauthorized"},
        )
    return user


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"error": "You do not have access to this session.", "code": "forbidden"},
    )


def assert_session_access(
    session_id: str,
    user: UserRecord | None,
    client_id: str | None = None,
) -> None:
    """Authorize access to an upload session and everything stored inside it.

    Enforced whether or not OAuth is configured: with OAuth off, sessions are
    owned by the anonymous client cookie instead, so one browser cannot read
    another's uploads by guessing a file id.
    """
    owner = upload_session_owner(session_id)
    if owner is None:
        raise _forbidden()
    if owner.user_id is not None:
        if user is None or owner.user_id != user.id:
            raise _forbidden()
        return
    if owner.client_id is None or client_id is None or not secrets.compare_digest(owner.client_id, client_id):
        raise _forbidden()


def assert_file_access(
    session_id: str,
    user: UserRecord | None,
    client_id: str | None = None,
) -> None:
    assert_session_access(session_id, user, client_id)


def register_session_owner(
    session_id: str,
    user: UserRecord | None,
    client_id: str | None,
) -> None:
    if user is not None:
        register_upload_session(session_id, user_id=user.id)
    else:
        register_upload_session(session_id, client_id=client_id)


def build_google_login_url(return_url: str | None = None) -> str:
    if not auth_enabled():
        raise RuntimeError("Google OAuth is not configured.")

    target = return_url or frontend_url()
    state = create_oauth_state(target)
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def complete_google_login(code: str, state: str) -> tuple[UserRecord, str, str]:
    return_url = consume_oauth_state(state)
    if return_url is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid or expired OAuth state.", "code": "invalid_oauth_state"},
        )

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri": google_redirect_uri(),
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail={"error": "Google token exchange failed.", "code": "oauth_token_error"},
            )

        access_token = token_response.json().get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=400,
                detail={"error": "Google did not return an access token.", "code": "oauth_token_error"},
            )

        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail={"error": "Could not load Google profile.", "code": "oauth_profile_error"},
            )

    profile = userinfo_response.json()
    google_sub = profile.get("sub")
    email = profile.get("email")
    name = profile.get("name") or email
    if not google_sub or not email:
        raise HTTPException(
            status_code=400,
            detail={"error": "Google profile is missing required fields.", "code": "oauth_profile_error"},
        )

    user = upsert_google_user(
        google_sub=str(google_sub),
        email=str(email),
        name=str(name),
        picture_url=str(profile["picture"]) if profile.get("picture") else None,
    )
    session_token = create_auth_session(user.id, ttl_hours=auth_session_ttl_hours())
    return user, session_token, return_url


def safe_return_url(request: Request) -> str:
    candidate = request.query_params.get("return_url")
    if not candidate:
        return frontend_url()
    if not candidate.startswith(frontend_url()):
        return frontend_url()
    return candidate


def generate_auth_secret_if_missing() -> None:
    if os.environ.get("AUTH_SECRET"):
        return
    os.environ["AUTH_SECRET"] = secrets.token_urlsafe(32)


# --- Ownership for saved content pieces and storage quota -------------------


@dataclass(frozen=True)
class Owner:
    """Who a saved piece or upload belongs to: a Google user, else a browser."""

    user_id: str | None
    client_id: str | None

    @property
    def key(self) -> str:
        return self.user_id or f"anon:{self.client_id}"


def require_owner(
    user: UserRecord | None = Depends(get_current_user_optional),
    client_id: str | None = Depends(get_client_id_optional),
) -> Owner:
    if auth_enabled():
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "Sign in required.", "code": "unauthorized"},
            )
        return Owner(user_id=user.id, client_id=None)
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "No client session. Create an upload session first.",
                "code": "no_client_session",
            },
        )
    return Owner(user_id=None, client_id=client_id)

