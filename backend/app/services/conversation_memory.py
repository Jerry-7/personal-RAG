"""Bounded conversation context with a persisted rolling summary."""

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ConversationSummary, Message


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

    def update_summary(self, db: Session, conversation_id: str) -> ConversationSummary | None:
        messages = (
            db.query(Message).filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc()).all()
        )
        total_chars = sum(len(message.content) for message in messages)
        if len(messages) <= 12 and total_chars <= settings.agent_context_max_chars:
            return None
        old_messages = messages[:-self.recent_message_count]
        if not old_messages:
            return None
        lines = []
        for message in old_messages:
            label = "User" if message.role == "user" else "Assistant"
            compact = " ".join(message.content.split())
            lines.append(f"{label}: {compact[:800]}")
        summary_text = "\n".join(lines)[-12000:]
        summary = db.query(ConversationSummary).filter_by(conversation_id=conversation_id).first()
        if summary is None:
            summary = ConversationSummary(conversation_id=conversation_id)
            db.add(summary)
        summary.summary = summary_text
        summary.through_message_id = old_messages[-1].id
        summary.message_count = len(old_messages)
        db.commit()
        return summary


conversation_memory = ConversationMemoryService()
