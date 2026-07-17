# Personal RAG - 后台任务管理器
"""
后台任务管理器模块

使用 asyncio.Semaphore 控制并发索引任务数量。
通过 asyncio.create_task 在后台执行索引流水线。

全局单例 task_manager 在应用生命周期内管理所有后台任务。
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class TaskManager:
    """
    后台任务管理器。

    使用 Semaphore 限制并发数，asyncio.create_task 执行后台任务。
    每个任务对应一个 doc_id，可单独取消。

    Attributes:
        _semaphore: 控制并发数的信号量
        _tasks: doc_id → asyncio.Task 映射（仅运行中的任务）
        _shutting_down: 是否正在关闭，关闭时拒绝新任务
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        """
        初始化任务管理器。

        Args:
            max_concurrent: 最大并发任务数，默认 10
        """
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._shutting_down: bool = False

    # ── 公开 API ─────────────────────────────────────────────

    @property
    def active_count(self) -> int:
        """当前进行中的任务数（等待 + 运行中）。"""
        return len(self._tasks)

    def can_accept(self) -> bool:
        """是否可以接受新任务（未关闭且有空位）。"""
        return not self._shutting_down and self.active_count < self._max_concurrent

    @property
    def max_concurrent(self) -> int:
        """最大并发任务数。"""
        return self._max_concurrent

    @property
    def is_shutting_down(self) -> bool:
        """是否正在关闭。"""
        return self._shutting_down

    async def submit(
        self,
        doc_id: str,
        coro_factory: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """
        提交后台任务。

        使用 coro_factory 模式避免在 semaphore 获取前创建协程。
        任务完成后自动释放 semaphore。

        Args:
            doc_id: 文档唯一 ID
            coro_factory: 返回协程的工厂函数，在 semaphore 获取后调用

        Raises:
            RuntimeError: 正在关闭或队列已满
        """
        if self._shutting_down:
            raise RuntimeError("任务管理器正在关闭，拒绝新任务")

        if not self.can_accept():
            raise RuntimeError(
                f"索引队列已满 ({self.active_count}/{self.max_concurrent})，请稍后再试"
            )

        async def _runner() -> None:
            """包装器：获取信号量、执行任务、释放信号量。"""
            async with self._semaphore:
                if self._shutting_down:
                    return
                try:
                    coro = coro_factory()
                    await coro
                except Exception:
                    logger.exception(f"后台任务异常, doc_id={doc_id}")
                finally:
                    self._tasks.pop(doc_id, None)

        task = asyncio.create_task(_runner())
        self._tasks[doc_id] = task

    def cancel(self, doc_id: str) -> bool:
        """
        取消指定文档的后台任务。

        Args:
            doc_id: 文档唯一 ID

        Returns:
            是否成功取消（任务存在且未完成）
        """
        task = self._tasks.get(doc_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def shutdown(self, timeout: float = 30.0) -> None:
        """
        优雅关闭：取消等待中任务，等待运行中任务完成。

        1. 设置关闭标志，拒绝新任务
        2. 取消所有运行中任务
        3. 等待最多 timeout 秒
        4. 记录未能完成的任务

        Args:
            timeout: 等待运行中任务完成的超时时间（秒）
        """
        logger.info(f"正在关闭任务管理器 (活跃任务: {self.active_count})...")
        self._shutting_down = True

        # 取消所有运行中的任务
        for doc_id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
                logger.info(f"已取消后台任务: {doc_id}")

        # 等待任务完成（被取消也算完成）
        if self._tasks:
            remaining = list(self._tasks.values())
            try:
                await asyncio.wait(remaining, timeout=timeout)
            except Exception:
                pass

        # 检查未完成的任务
        unfinished = [did for did, t in self._tasks.items() if not t.done()]
        if unfinished:
            logger.warning(
                f"以下后台任务未能在 {timeout}s 内完成: {unfinished}"
            )

        logger.info("任务管理器已关闭")


# 全局单例
task_manager = TaskManager(
    max_concurrent=settings.max_concurrent_indexing_tasks,
)
