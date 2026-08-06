"""Request-scoped state used while executing an Agent run."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class AgentRunContext:
    """Explicit request context passed to every built-in Agent tool."""

    db: Session
    conversation_id: str
    run_id: str = ""
    mode: str = "auto"
    allowed_tool_sources: frozenset[str] | None = None
    cancellation_event: Any | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    citation_counter: int = 0
    web_page_budget: int = 8
    web_pages_used: int = 0
    max_crawl_depth: int = 2
    visited_urls: set[str] = field(default_factory=set)
    web_search_performed: bool = False
    tool_output_chars: int = 0
    max_tool_output_chars: int = 40000

    def is_cancelled(self) -> bool:
        return bool(self.cancellation_event and self.cancellation_event.is_set())

    def register_source(self, source: dict[str, Any]) -> int:
        self.citation_counter += 1
        self.citations.append({"index": self.citation_counter, **source})
        return self.citation_counter

    def can_fetch_page(self) -> bool:
        return self.web_pages_used < self.web_page_budget

    def can_use_tool_source(self, source: str) -> bool:
        """Return whether the selected Agent profile may use a tool source."""
        return self.allowed_tool_sources is None or source in self.allowed_tool_sources
