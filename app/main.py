from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, init_db
from app.models import TikTokAccount
from app.queue import tasks
from app.queue.worker import get_queue_worker
from app.tiktok import oauth
from app.utils.logging import configure_logging

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="tg2tiktok-poster", version="1.0.0")


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    Path(settings.media_storage_path).mkdir(parents=True, exist_ok=True)
    await get_queue_worker().start()
    logger.info(
        "service_started",
        extra={
            "event": "startup",
        },
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await get_queue_worker().stop()


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/tg/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request) -> dict[str, bool]:
    if secret != settings.tg_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    update = await request.json()
    await tasks.ingest_update(update)
    return {"ok": True}


@app.get("/tiktok/auth/start")
async def tiktok_auth_start(
    account_label: str = Query(..., min_length=1),
    mode: Literal["draft", "direct"] = Query(settings.posting_mode),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    url = await oauth.build_authorization_url(
        db=db,
        account_label=account_label.strip(),
        mode=mode,
    )
    return RedirectResponse(url=url, status_code=307)


@app.get("/tiktok/auth/callback")
async def tiktok_auth_callback(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        account = await oauth.handle_callback(
            db=db,
            code=code,
            state=state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("oauth_callback_error", extra={"event": "oauth_callback_error"})
        raise HTTPException(status_code=502, detail=f"OAuth callback failed: {exc}") from exc

    return {
        "ok": True,
        "account_label": account.account_label,
        "open_id": account.open_id,
        "posting_mode": account.posting_mode,
        "needs_reauth": account.needs_reauth,
        "expires_at": account.expires_at.isoformat() if account.expires_at else None,
    }


@app.get("/admin/tiktok/accounts")
async def list_tiktok_accounts(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.scalars(select(TikTokAccount).order_by(TikTokAccount.account_label.asc())).all()
    return [
        {
            "account_label": row.account_label,
            "open_id": row.open_id,
            "posting_mode": row.posting_mode,
            "needs_reauth": row.needs_reauth,
            "granted_scopes": row.granted_scopes,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "token_present": bool(row.access_token),
        }
        for row in rows
    ]

