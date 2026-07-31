"""Request-scoped state used while executing an Agent run."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class AgentRunContext:
    """Explicit request context passed to every built-in Agent tool."""

    db: Session
    conversation_id: str
    cancellation_event: Any | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    citation_counter: int = 0

    def is_cancelled(self) -> bool:
        return bool(self.cancellation_event and self.cancellation_event.is_set())
