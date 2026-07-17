# Personal RAG - 内存事件总线
"""
内存事件总线模块

轻量级发布/订阅，基于 asyncio.Queue 实现。
每个文档 ID 对应一个 Queue，后台任务发布进度事件，
SSE 端点订阅并消费。

用于文档索引进度的实时推送，零外部依赖。
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """
    基于 asyncio.Queue 的内存发布/订阅。

    使用方式：
        # 发布者（后台索引任务）
        event_bus.publish(doc_id, {"event": "progress", "data": {...}})

        # 订阅者（SSE 端点）
        queue = event_bus.subscribe(doc_id)
        while True:
            event = await queue.get()
            ...

    Attributes:
        _subscribers: doc_id → asyncio.Queue 的映射
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    def subscribe(self, doc_id: str) -> asyncio.Queue[dict[str, Any]]:
        """
        订阅指定文档的进度事件。

        如果该文档的队列尚不存在则创建，存在则复用。
        这允许 SSE 端点在任何时候订阅，即使后台任务已开始发布事件。

        Args:
            doc_id: 文档唯一 ID

        Returns:
            该文档对应的事件队列
        """
        if doc_id not in self._subscribers:
            self._subscribers[doc_id] = asyncio.Queue()
        return self._subscribers[doc_id]

    def unsubscribe(self, doc_id: str) -> None:
        """
        取消订阅并清理队列。

        在 SSE 客户端断开或事件流结束时调用。

        Args:
            doc_id: 文档唯一 ID
        """
        self._subscribers.pop(doc_id, None)

    def publish(self, doc_id: str, event: dict[str, Any]) -> None:
        """
        向指定文档的订阅者发布事件。

        使用 put_nowait() 不阻塞发布者。
        如果无人订阅，事件仍进入队列等待后续订阅者。

        Args:
            doc_id: 文档唯一 ID
            event: 事件字典，如 {"event": "progress", "data": {...}}
        """
        queue = self._subscribers.get(doc_id)
        if queue is None:
            queue = self.subscribe(doc_id)
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"事件队列已满, doc_id={doc_id}, 丢弃事件")

    def cleanup(self, doc_id: str) -> None:
        """
        清理完成/失败文档的订阅者队列。

        在后台任务完成（done/error）后调用，
        比 unsubscribe 更明确地表示"不再有事件"。

        Args:
            doc_id: 文档唯一 ID
        """
        self.unsubscribe(doc_id)

    @property
    def active_count(self) -> int:
        """当前活跃的订阅者数量。"""
        return len(self._subscribers)


# 全局单例
event_bus = EventBus()
