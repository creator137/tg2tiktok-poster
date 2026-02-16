from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

TIKTOK_OPEN_API_BASE = "https://open.tiktokapis.com"
TIKTOK_AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"

OAUTH_TOKEN_ENDPOINT = "/v2/oauth/token/"
USER_INFO_ENDPOINT = "/v2/user/info/"

VIDEO_INIT_ENDPOINT = "/v2/post/publish/video/init/"
VIDEO_FINALIZE_ENDPOINT = "/v2/post/publish/video/publish/"

# Optional / may not be available for every app scope or TikTok program.
PHOTO_INIT_ENDPOINT = "/v2/post/publish/content/init/"
PHOTO_FINALIZE_ENDPOINT = "/v2/post/publish/content/publish/"


class TikTokAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}

    def is_unsupported_or_permission(self) -> bool:
        text = str(self).lower()
        markers = (
            "unsupported",
            "not support",
            "permission",
            "scope",
            "forbidden",
            "insufficient",
            "not authorized",
            "not available",
        )
        if self.status_code in {403, 404}:
            return True
        if any(marker in text for marker in markers):
            return True
        error_text = str(self.payload).lower()
        return any(marker in error_text for marker in markers)


class TikTokClient:
    def __init__(self, timeout: float = 120.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "TikTokClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def exchange_code_for_token(
        self,
        *,
        client_key: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            OAUTH_TOKEN_ENDPOINT,
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return _unwrap_data(payload)

    async def refresh_access_token(
        self,
        *,
        client_key: str,
        client_secret: str,
        refresh_token: str,
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            OAUTH_TOKEN_ENDPOINT,
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return _unwrap_data(payload)

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            USER_INFO_ENDPOINT,
            access_token=access_token,
            json_body={"fields": ["open_id", "union_id", "display_name"]},
        )
        return _unwrap_data(payload)

    async def init_video_upload(
        self,
        *,
        access_token: str,
        caption: str,
        mode: str,
        video_size_bytes: int,
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            VIDEO_INIT_ENDPOINT,
            access_token=access_token,
            json_body={
                "post_mode": mode,
                "post_info": {
                    "title": caption,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size_bytes,
                },
            },
        )
        return _unwrap_data(payload)

    async def finalize_video(
        self,
        *,
        access_token: str,
        publish_id: str | None,
        caption: str,
        mode: str,
    ) -> dict[str, Any]:
        if not publish_id:
            return {}
        payload = await self._request(
            "POST",
            VIDEO_FINALIZE_ENDPOINT,
            access_token=access_token,
            json_body={
                "publish_id": publish_id,
                "post_mode": mode,
                "post_info": {
                    "title": caption,
                },
            },
        )
        return _unwrap_data(payload)

    async def init_photo_upload(
        self,
        *,
        access_token: str,
        caption: str,
        mode: str,
        media_count: int,
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            PHOTO_INIT_ENDPOINT,
            access_token=access_token,
            json_body={
                "post_mode": mode,
                "post_info": {
                    "title": caption,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "media_count": media_count,
                    "media_type": "PHOTO",
                },
            },
        )
        return _unwrap_data(payload)

    async def finalize_photo_upload(
        self,
        *,
        access_token: str,
        publish_id: str | None,
        caption: str,
        mode: str,
    ) -> dict[str, Any]:
        if not publish_id:
            return {}
        payload = await self._request(
            "POST",
            PHOTO_FINALIZE_ENDPOINT,
            access_token=access_token,
            json_body={
                "publish_id": publish_id,
                "post_mode": mode,
                "post_info": {
                    "title": caption,
                },
            },
        )
        return _unwrap_data(payload)

    async def upload_binary(
        self,
        upload_url: str,
        file_path: Path,
        *,
        content_type: str,
    ) -> None:
        response = await self._client.put(
            upload_url,
            content=file_path.read_bytes(),
            headers={"Content-Type": content_type},
            timeout=300,
        )
        if response.status_code >= 400:
            raise TikTokAPIError(
                f"Binary upload failed: HTTP {response.status_code}",
                status_code=response.status_code,
                payload=_safe_json(response),
            )

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        access_token: str | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = _build_url(path_or_url)
        request_headers = headers.copy() if headers else {}
        if access_token:
            request_headers["Authorization"] = f"Bearer {access_token}"

        response = await self._client.request(
            method=method,
            url=url,
            json=json_body,
            data=data,
            headers=request_headers,
        )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise TikTokAPIError(
                f"TikTok API HTTP {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        _raise_if_api_error(payload)
        return payload


def _build_url(path_or_url: str) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    return f"{TIKTOK_OPEN_API_BASE}{path_or_url}"


def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {"raw": response.text}
    if isinstance(data, dict):
        return data
    return {"raw": data}


def _raise_if_api_error(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    error = payload.get("error")
    if error:
        raise TikTokAPIError(f"TikTok API error: {error}", payload=payload)

    error_code = payload.get("error_code")
    if error_code not in (None, 0, "0"):
        raise TikTokAPIError(f"TikTok API error_code={error_code}", payload=payload)

