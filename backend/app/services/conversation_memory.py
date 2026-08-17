"""Conversation context with a persisted Agent-compressed rolling summary."""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ConversationSummary, Message
from app.providers.base import LLMProvider
from app.services.context_compression import (
    CompressionStats,
    ContextCompressor,
    estimate_tokens,
)


@dataclass(frozen=True)
class ConversationSummaryUpdate:
    summary: ConversationSummary
    stats: CompressionStats


class ConversationMemoryService:
    recent_message_count = 6

    def get_context(
        self, db: Session, conversation_id: str, exclude_message_id: str | None = None
    ) -> list[dict[str, str]]:
        messages = (
            db.query(Message).filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc()).all()
        )
        if exclude_message_id:
            messages = [message for message in messages if message.id != exclude_message_id]
        summary = db.query(ConversationSummary).filter_by(conversation_id=conversation_id).first()
        context: list[dict[str, str]] = []
        if summary and summary.summary:
            context.append({"role": "system", "content": f"Earlier conversation summary:\n{summary.summary}"})
            ids = [message.id for message in messages]
            if summary.through_message_id in ids:
                messages = messages[ids.index(summary.through_message_id) + 1:]
        context.extend({"role": message.role, "content": message.content} for message in messages)
        return context

    def get_context_before(
        self,
        db: Session,
        conversation_id: str,
        before_message: Message,
    ) -> list[dict[str, str]]:
        """Rebuild context as it existed immediately before a stored message."""
        messages = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.created_at < before_message.created_at,
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        summary = db.query(ConversationSummary).filter_by(
            conversation_id=conversation_id
        ).first()
        context: list[dict[str, str]] = []
        if summary and summary.summary:
            ids = [message.id for message in messages]
            if summary.through_message_id in ids:
                context.append({
                    "role": "system",
                    "content": f"Earlier conversation summary:\n{summary.summary}",
                })
                messages = messages[ids.index(summary.through_message_id) + 1:]
        context.extend(
            {"role": message.role, "content": message.content}
            for message in messages
        )
        return context

    async def update_summary(
        self,
        db: Session,
        conversation_id: str,
        provider: LLMProvider,
        *,
        model_name: str | None = None,
    ) -> ConversationSummaryUpdate | None:
        messages = (
            db.query(Message).filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc()).all()
        )
        total_tokens = sum(estimate_tokens(message.content) for message in messages)
        if len(messages) <= 12 and total_tokens <= settings.agent_context_max_tokens:
            return None
        old_messages = messages[:-self.recent_message_count]
        if not old_messages:
            return None
        source = "\n\n".join(
            (
                f"<message index={index} role={json.dumps(message.role)}>\n"
                f"{message.content or ''}\n"
                "</message>"
            )
            for index, message in enumerate(old_messages, start=1)
        )
        compressed = await ContextCompressor(
            provider,
            model_name=model_name,
        ).compress_text(
            source,
            target_tokens=settings.agent_memory_summary_max_tokens,
            purpose="persisted conversation memory",
        )
        summary = db.query(ConversationSummary).filter_by(conversation_id=conversation_id).first()
        if summary is None:
            summary = ConversationSummary(conversation_id=conversation_id)
            db.add(summary)
        summary.summary = compressed.content
        summary.through_message_id = old_messages[-1].id
        summary.message_count = len(old_messages)
        db.commit()
        db.refresh(summary)
        return ConversationSummaryUpdate(summary, compressed.stats)


conversation_memory = ConversationMemoryService()
