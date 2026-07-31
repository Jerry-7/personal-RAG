"""Bounded, SSRF-safe HTML/PDF fetching for research tools."""

import asyncio
import hashlib
import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from app.config import settings


USER_AGENT = "PersonalResearchAgent/0.2"


@dataclass
class FetchedPage:
    url: str
    title: str
    content: str
    content_type: str
    status_code: int
    content_hash: str
    links: list[str]


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data.strip())


class WebFetcher:
    def __init__(self) -> None:
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    @staticmethod
    def canonicalize(url: str) -> str:
        url, _ = urldefrag(url.strip())
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"}:
            raise ValueError("仅支持 HTTP(S) URL")
        if parts.username or parts.password:
            raise ValueError("URL 不允许包含凭据")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise ValueError("URL 缺少主机名")
        port = parts.port
        netloc = f"[{host}]" if ":" in host else host
        if port and not ((parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)):
            netloc = f"{host}:{port}"
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))

    async def validate_public_url(self, url: str) -> str:
        canonical = self.canonicalize(url)
        host = urlsplit(canonical).hostname or ""
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
        if not infos:
            raise ValueError("域名无法解析")
        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if not address.is_global:
                raise ValueError("禁止访问内网、回环或保留地址")
        return canonical

    async def _rate_limit(self, host: str) -> None:
        lock = self._domain_locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = 1.0 - (time.monotonic() - self._last_request.get(host, 0.0))
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request[host] = time.monotonic()

    async def _robots_allowed(self, url: str, client: httpx.AsyncClient) -> bool:
        parts = urlsplit(url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            await self._rate_limit(parts.hostname or "")
            response = await client.get(robots_url, headers={"User-Agent": USER_AGENT})
            if response.status_code >= 400:
                return True
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text[:262144].splitlines())
            return parser.can_fetch(USER_AGENT, url)
        except httpx.HTTPError:
            return True

    async def fetch(self, url: str, *, check_robots: bool = True) -> FetchedPage:
        current = await self.validate_public_url(url)
        timeout = httpx.Timeout(settings.web_fetch_timeout_secs)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            if check_robots and not await self._robots_allowed(current, client):
                raise PermissionError("robots.txt 不允许抓取该页面")
            response_status = 0
            response_encoding = "utf-8"
            content_type = ""
            body = b""
            completed = False
            for _ in range(4):
                host = urlsplit(current).hostname or ""
                await self._rate_limit(host)
                async with client.stream("GET", current, headers={"User-Agent": USER_AGENT}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("重定向响应缺少 Location")
                        current = await self.validate_public_url(urljoin(current, location))
                        if check_robots and not await self._robots_allowed(current, client):
                            raise PermissionError("robots.txt 不允许抓取重定向后的页面")
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    max_bytes = settings.web_pdf_max_bytes if content_type == "application/pdf" else settings.web_html_max_bytes
                    declared_size = int(response.headers.get("content-length", "0") or 0)
                    if declared_size > max_bytes:
                        raise ValueError("网页内容超过大小限制")
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("网页内容超过大小限制")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    response_status = response.status_code
                    response_encoding = response.encoding or "utf-8"
                    completed = True
                    break
            if not completed:
                raise ValueError("网页重定向次数超过限制")

        links: list[str] = []
        if content_type == "application/pdf" or current.lower().endswith(".pdf"):
            import fitz
            document = fitz.open(stream=body, filetype="pdf")
            text_content = "\n\n".join(page.get_text() for page in document)
            title = current.rsplit("/", 1)[-1]
            content_type = "application/pdf"
        else:
            html = body.decode(response_encoding, errors="replace")
            parser = _LinkParser()
            parser.feed(html)
            title = " ".join(part for part in parser.title_parts if part).strip()
            text_content = trafilatura.extract(
                html, include_comments=False, include_tables=True, output_format="txt"
            ) or re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
            links = list(dict.fromkeys(urljoin(current, link) for link in parser.links))

        text_content = text_content.strip()
        if not text_content:
            raise ValueError("未能提取网页正文")
        return FetchedPage(
            url=current,
            title=title or current,
            content=text_content,
            content_type=content_type or "text/html",
            status_code=response_status,
            content_hash=hashlib.sha256(text_content.encode("utf-8")).hexdigest(),
            links=links,
        )


web_fetcher = WebFetcher()
