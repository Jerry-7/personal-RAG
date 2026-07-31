"""Search-provider abstraction and SearXNG implementation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str = ""
    published_at: str | None = None


class SearchProvider(ABC):
    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        language: str = "all",
        time_range: str | None = None,
        max_results: int = 5,
    ) -> list[SearchResult]: ...

    @abstractmethod
    async def health(self) -> bool: ...


class SearXNGProvider(SearchProvider):
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.searxng_base_url).rstrip("/")

    async def search(
        self,
        query: str,
        *,
        language: str = "all",
        time_range: str | None = None,
        max_results: int = 5,
    ) -> list[SearchResult]:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": language or settings.web_search_language,
            "safesearch": settings.web_safe_search,
        }
        if time_range in {"day", "month", "year"}:
            params["time_range"] = time_range
        async with httpx.AsyncClient(timeout=settings.web_fetch_timeout_secs) as client:
            response = await client.get(f"{self.base_url}/search", params=params)
            response.raise_for_status()
            payload = response.json()
        results: list[SearchResult] = []
        for item in payload.get("results", [])[:max(1, min(max_results, 10))]:
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            results.append(SearchResult(
                title=str(item.get("title", url)),
                url=url,
                snippet=str(item.get("content", "")),
                engine=str(item.get("engine", "")),
                published_at=item.get("publishedDate"),
            ))
        return results

    async def health(self) -> bool:
        try:
            await self.search("health", max_results=1)
            return True
        except Exception:
            return False


search_provider: SearchProvider = SearXNGProvider()
