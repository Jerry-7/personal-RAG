"""Persistence, citation registration, and bounded site research."""

import re
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from app.agent.context import AgentRunContext
from app.config import settings
from app.db.models import AgentRun, ResearchRunSnapshot, WebSnapshot
from app.services.web_fetcher import FetchedPage, web_fetcher


class WebResearchService:
    @staticmethod
    def _excerpt(content: str, objective: str, limit: int = 3500) -> str:
        terms = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", objective.lower()))
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", content) if part.strip()]
        ranked = sorted(
            enumerate(paragraphs),
            key=lambda item: sum(term in item[1].lower() for term in terms),
            reverse=True,
        )
        selected: list[str] = []
        length = 0
        for _, paragraph in ranked:
            if length + len(paragraph) > limit:
                paragraph = paragraph[: max(0, limit - length)]
            if paragraph:
                selected.append(paragraph)
                length += len(paragraph)
            if length >= limit:
                break
        return "\n\n".join(selected) or content[:limit]

    async def fetch_and_store(
        self,
        context: AgentRunContext,
        url: str,
        objective: str,
        *,
        depth: int = 0,
    ) -> tuple[FetchedPage, WebSnapshot, int]:
        if not context.can_fetch_page():
            raise RuntimeError("已达到本次研究的网页读取预算")
        canonical = web_fetcher.canonicalize(url)
        if canonical in context.visited_urls:
            snapshot = (
                context.db.query(WebSnapshot)
                .filter(WebSnapshot.canonical_url == canonical)
                .order_by(WebSnapshot.fetched_at.desc())
                .first()
            )
            if snapshot is None:
                raise RuntimeError("该网页已访问但快照不存在")
            page = FetchedPage(
                url=snapshot.canonical_url, title=snapshot.title, content=snapshot.content,
                content_type=snapshot.content_type, status_code=snapshot.http_status,
                content_hash=snapshot.content_hash, links=[],
            )
        else:
            page = await web_fetcher.fetch(canonical)
            context.visited_urls.add(page.url)
            context.web_pages_used += 1
            snapshot = (
                context.db.query(WebSnapshot)
                .filter(
                    WebSnapshot.canonical_url == page.url,
                    WebSnapshot.content_hash == page.content_hash,
                )
                .first()
            )
            if snapshot is None:
                snapshot = WebSnapshot(
                    canonical_url=page.url,
                    title=page.title,
                    content=page.content,
                    content_hash=page.content_hash,
                    content_type=page.content_type,
                    http_status=page.status_code,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=settings.web_snapshot_retention_days),
                )
                context.db.add(snapshot)
                context.db.flush()
            if context.run_id:
                exists = context.db.query(ResearchRunSnapshot).filter(
                    ResearchRunSnapshot.run_id == context.run_id,
                    ResearchRunSnapshot.snapshot_id == snapshot.id,
                ).first()
                if exists is None:
                    context.db.add(ResearchRunSnapshot(
                        run_id=context.run_id, snapshot_id=snapshot.id, depth=depth
                    ))
                run = context.db.query(AgentRun).filter(AgentRun.id == context.run_id).first()
                if run:
                    run.web_pages_used = context.web_pages_used
            context.db.commit()

        citation_index = context.register_source({
            "document_id": "",
            "chunk_id": "",
            "snapshot_id": snapshot.id,
            "snippet": self._excerpt(snapshot.content, objective, 240),
            "filename": snapshot.title,
            "title": snapshot.title,
            "url": snapshot.canonical_url,
            "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
            "content_hash": snapshot.content_hash,
            "source_type": "web",
        })
        return page, snapshot, citation_index

    async def crawl(
        self,
        context: AgentRunContext,
        start_url: str,
        objective: str,
    ) -> list[tuple[FetchedPage, WebSnapshot, int, int]]:
        start = web_fetcher.canonicalize(start_url)
        host = urlsplit(start).hostname
        queue = deque([(start, 0)])
        queued = {start}
        results: list[tuple[FetchedPage, WebSnapshot, int, int]] = []
        while queue and context.can_fetch_page():
            url, depth = queue.popleft()
            try:
                page, snapshot, citation = await self.fetch_and_store(
                    context, url, objective, depth=depth
                )
            except Exception:
                if depth == 0:
                    raise
                continue
            results.append((page, snapshot, citation, depth))
            if depth >= context.max_crawl_depth:
                continue
            for link in page.links:
                try:
                    canonical = web_fetcher.canonicalize(link)
                except ValueError:
                    continue
                if urlsplit(canonical).hostname != host or canonical in queued or canonical in context.visited_urls:
                    continue
                queued.add(canonical)
                queue.append((canonical, depth + 1))
        return results


web_research_service = WebResearchService()
