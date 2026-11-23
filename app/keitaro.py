"""Async client for the Keitaro Admin API."""

import random
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeitaroSettings(BaseSettings):
    """Keitaro Admin API settings (env: KEITARO_URL, KEITARO_API_KEY)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    keitaro_url: str = ""
    keitaro_api_key: str = ""
    use_keitaro_mock: bool = False

    @property
    def base_url(self) -> str:
        """Base URL of the Keitaro instance without trailing slash."""
        return self.keitaro_url.rstrip("/")


class KeitaroAPIError(Exception):
    """Raised when the Keitaro Admin API returns a 4xx or 5xx response."""

    def __init__(self, status_code: int, response_body: str) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"Keitaro API error {status_code}: {response_body}")


_MOCK_CAMPAIGNS: dict[int, dict] = {}
"""In-memory mock campaigns: {keitaro_campaign_id: {...}}."""

_MOCK_STREAMS: dict[int, dict] = {}
"""In-memory mock streams: {stream_id: {...}}."""


class KeitaroClient:
    """Async HTTP client for the Keitaro Admin API.

    All requests go to ``{base_url}/admin_api/v1/`` with the ``Api-Key`` header.
    """

    DEFAULT_TIMEOUT: float = 30.0

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/admin_api/v1/",
            headers={"Api-Key": self.api_key},
            timeout=httpx.Timeout(self.DEFAULT_TIMEOUT),
        )

    async def aclose(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._client.aclose()

    async def __aenter__(self) -> "KeitaroClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Perform an async request, raise KeitaroAPIError on HTTP errors."""
        response = await self._client.request(method, url, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KeitaroAPIError(
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        if not response.content:
            return None
        return response.json()

    async def create_campaign(self, payload: dict) -> dict:
        """Create a campaign."""
        if KeitaroSettings().use_keitaro_mock:
            campaign_id = random.randint(10**9, 10**10)
            _MOCK_CAMPAIGNS[campaign_id] = {
                "id": campaign_id,
                "keitaro_id": campaign_id,
                "name": payload.get("name"),
                "geo": payload.get("geo"),
                "offer_id": payload.get("offer_id"),
            }
            print(f"[MOCK] create_campaign -> id={campaign_id}")
            return {"id": campaign_id}
        data = await self._request("POST", "/campaigns", json=payload)
        return data or {}

    async def get_campaign(self, campaign_id: int) -> dict:
        """Fetch a single campaign by ID."""
        if KeitaroSettings().use_keitaro_mock:
            print(f"[MOCK] get_campaign -> id={campaign_id}")
            return _MOCK_CAMPAIGNS.get(campaign_id, {})
        data = await self._request("GET", f"/campaigns/{campaign_id}")
        return data or {}

    async def list_campaigns(self, limit: int = 100, offset: int = 0) -> list:
        """List campaigns with pagination."""
        data = await self._request(
            "GET",
            "/campaigns",
            params={"limit": limit, "offset": offset},
        )
        if KeitaroSettings().use_keitaro_mock:
            print("[MOCK] list_campaigns called")
            return list(_MOCK_CAMPAIGNS.values())
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("campaigns") or []
        return []

    async def create_stream(self, payload: dict) -> dict:
        """Create a stream."""
        if KeitaroSettings().use_keitaro_mock:
            stream_id = random.randint(10**9, 10**10)
            _MOCK_STREAMS[stream_id] = {
                "id": stream_id,
                "campaign_id": payload.get("campaign_id"),
                "kind": "google" if payload.get("schema") == "redirect" else "offer",
                "offer_id": (payload.get("offers") or [{}])[0].get("offer_id"),
            }
            print(f"[MOCK] create_stream -> id={stream_id} campaign={payload.get('campaign_id')}")
            return {"id": stream_id}
        data = await self._request("POST", "/streams", json=payload)
        return data or {}

    async def delete_stream(self, stream_id: int) -> None:
        """Delete a stream by ID."""
        if KeitaroSettings().use_keitaro_mock:
            _MOCK_STREAMS.pop(stream_id, None)
            print(f"[MOCK] delete_stream {stream_id}")
            return None
        await self._request("DELETE", f"/streams/{stream_id}")

    async def list_streams(self, campaign_id: int) -> list:
        """List streams of a campaign."""
        if KeitaroSettings().use_keitaro_mock:
            print(f"[MOCK] list_streams -> campaign={campaign_id}")
            return [s for s in _MOCK_STREAMS.values() if s["campaign_id"] == campaign_id]
        data = await self._request("GET", f"/campaigns/{campaign_id}/streams")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("streams") or []
        return []

    async def delete_campaign(self, campaign_id: int) -> None:
        """Delete a campaign."""
        if KeitaroSettings().use_keitaro_mock:
            _MOCK_CAMPAIGNS.pop(campaign_id, None)
            print(f"[MOCK] delete_campaign {campaign_id}")
            return None
        await self._request("DELETE", f"/campaigns/{campaign_id}")


_keitaro_client: KeitaroClient | None = None


def get_keitaro_client() -> KeitaroClient:
    """Return a KeitaroClient configured from KEITARO_URL / KEITARO_API_KEY settings."""
    global _keitaro_client
    if _keitaro_client is None:
        settings = KeitaroSettings()
        _keitaro_client = KeitaroClient(
            base_url=settings.keitaro_url,
            api_key=settings.keitaro_api_key,
        )
    return _keitaro_client


async def aclose_cached_client() -> None:
    """Close and reset the cached KeitaroClient."""
    global _keitaro_client
    if _keitaro_client is not None:
        await _keitaro_client.aclose()
        _keitaro_client = None
