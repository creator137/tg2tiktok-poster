from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import OAuthState, TikTokAccount, utcnow
from app.tiktok.client import TIKTOK_AUTHORIZE_URL, TikTokAPIError, TikTokClient

logger = logging.getLogger(__name__)

settings = get_settings()

MODE_SCOPES: dict[str, str] = {
    "draft": "user.info.basic,video.upload",
    "direct": "user.info.basic,video.upload,video.publish",
}


async def build_authorization_url(db: Session, account_label: str, mode: str) -> str:
    if mode not in {"draft", "direct"}:
        raise ValueError("mode must be draft or direct")
    if not account_label.strip():
        raise ValueError("account_label is required")
    if not settings.tiktok_client_key:
        raise ValueError("TIKTOK_CLIENT_KEY is empty")

    state = secrets.token_urlsafe(24)
    db.add(
        OAuthState(
            state=state,
            account_label=account_label.strip(),
            mode=mode,
            used=False,
        )
    )
    db.commit()

    query = urlencode(
        {
            "client_key": settings.tiktok_client_key,
            "response_type": "code",
            "scope": MODE_SCOPES[mode],
            "redirect_uri": settings.tiktok_redirect_uri,
            "state": state,
        }
    )
    return f"{TIKTOK_AUTHORIZE_URL}?{query}"


async def handle_callback(db: Session, code: str, state: str) -> TikTokAccount:
    oauth_state = db.scalar(
        select(OAuthState).where(OAuthState.state == state, OAuthState.used.is_(False))
    )
    if oauth_state is None:
        raise ValueError("Invalid or already used OAuth state")

    if not settings.tiktok_client_secret:
        raise ValueError("TIKTOK_CLIENT_SECRET is empty")

    async with TikTokClient() as client:
        token_data = await client.exchange_code_for_token(
            client_key=settings.tiktok_client_key,
            client_secret=settings.tiktok_client_secret,
            code=code,
            redirect_uri=settings.tiktok_redirect_uri,
        )

    access_token = str(token_data.get("access_token") or "").strip()
    refresh_token = str(token_data.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        raise ValueError("OAuth token response does not contain access_token/refresh_token")

    open_id = str(token_data.get("open_id") or "").strip() or None
    expires_in = _safe_int(token_data.get("expires_in"), default=3600)
    scope = token_data.get("scope") or token_data.get("granted_scopes")
    granted_scopes = ",".join(scope) if isinstance(scope, list) else str(scope or "")

    account = db.scalar(
        select(TikTokAccount).where(TikTokAccount.account_label == oauth_state.account_label)
    )
    if account is None:
        account = TikTokAccount(account_label=oauth_state.account_label)
        db.add(account)

    account.open_id = open_id
    account.access_token = access_token
    account.refresh_token = refresh_token
    account.expires_at = utcnow() + timedelta(seconds=max(60, expires_in))
    account.granted_scopes = granted_scopes
    account.posting_mode = oauth_state.mode
    account.needs_reauth = False

    oauth_state.used = True
    db.commit()
    db.refresh(account)
    return account


async def ensure_valid_access_token(db: Session, account: TikTokAccount) -> str:
    if account.needs_reauth:
        raise ValueError(f"Account {account.account_label} requires re-auth")
    if not account.access_token:
        raise ValueError(f"Account {account.account_label} has no access_token")

    expires_at = account.expires_at
    if expires_at and expires_at > (utcnow() + timedelta(seconds=90)):
        return account.access_token

    if not account.refresh_token:
        account.needs_reauth = True
        db.commit()
        raise ValueError(f"Account {account.account_label} has no refresh_token")

    try:
        async with TikTokClient() as client:
            token_data = await client.refresh_access_token(
                client_key=settings.tiktok_client_key,
                client_secret=settings.tiktok_client_secret,
                refresh_token=account.refresh_token,
            )
    except TikTokAPIError:
        account.needs_reauth = True
        db.commit()
        logger.exception(
            "refresh_token_failed",
            extra={"event": "refresh_token_failed", "account_label": account.account_label},
        )
        raise

    account.access_token = str(token_data.get("access_token") or account.access_token)
    account.refresh_token = str(token_data.get("refresh_token") or account.refresh_token)
    expires_in = _safe_int(token_data.get("expires_in"), default=3600)
    account.expires_at = utcnow() + timedelta(seconds=max(60, expires_in))
    account.needs_reauth = False
    db.commit()
    return account.access_token


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

