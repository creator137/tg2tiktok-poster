from __future__ import annotations

from typing import Any

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
GET_UPDATES_METHOD = "getUpdates"
GET_FILE_METHOD = "getFile"
SET_WEBHOOK_METHOD = "setWebhook"


class TelegramAPIError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, bot_token: str, timeout: float = 60.0) -> None:
        self.bot_token = bot_token
        self.base_url = f"{TELEGRAM_API_BASE}/bot{bot_token}"
        self.file_base_url = f"{TELEGRAM_API_BASE}/file/bot{bot_token}"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "TelegramClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        payload = await self._call(GET_UPDATES_METHOD, params=params)
        result = payload.get("result", [])
        return result if isinstance(result, list) else []

    async def get_file(self, file_id: str) -> dict[str, Any]:
        payload = await self._call(GET_FILE_METHOD, params={"file_id": file_id})
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramAPIError("Telegram getFile returned malformed payload")
        return result

    async def download_file(self, file_path: str) -> bytes:
        url = f"{self.file_base_url}/{file_path}"
        response = await self._client.get(url)
        if response.status_code >= 400:
            raise TelegramAPIError(f"Telegram file download failed: HTTP {response.status_code}")
        return response.content

    async def set_webhook(self, url: str, secret_token: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        return await self._call(SET_WEBHOOK_METHOD, params=payload)

    async def _call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{method}"
        response = await self._client.post(url, params=params, json=json_payload)
        data = _safe_json(response)
        if response.status_code >= 400:
            raise TelegramAPIError(f"Telegram API error HTTP {response.status_code}: {data}")
        if not data.get("ok", False):
            raise TelegramAPIError(f"Telegram API returned ok=false: {data}")
        return data


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"raw": response.text}
    if isinstance(payload, dict):
        return payload
    return {"raw": payload}

