import json

from app.agent.context import AgentRunContext
from app.agent.tools import tool_registry
from app.services.notes import note_service


async def _create_note_draft(*, context: AgentRunContext) -> str:
    note = note_service.create_draft_from_conversation(context.db, context.conversation_id)
    return json.dumps(note_service.serialize(context.db, note), ensure_ascii=False, default=str)


tool_registry.register(
    name="create_note_draft",
    description="将当前对话整理为可编辑的笔记草稿。仅创建草稿，不会发布或加入知识库。",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_create_note_draft,
    source="builtin",
)
