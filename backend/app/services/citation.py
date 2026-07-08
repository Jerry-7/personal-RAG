# Personal RAG - 引用解析服务
"""
引用解析模块

从 LLM 流式输出中实时检测 [N] 引用标记，
维护文本缓冲区和引用索引映射。
"""

import re
from typing import Any

# 匹配 [N] 引用格式的正则（N 为数字）
CITATION_PATTERN = re.compile(r"\[(\d+)\]")


class CitationParser:
    """
    引用解析器。

    在流式 token 输出中逐字符检测 [N] 格式的引用标记。
    当检测到完整的引用标记时，emit citation 事件，
    其余文本 emit token 事件。

    Attributes:
        _buffer: 字符缓冲区，用于检测不完整的引用格式
        _citations: 已检测到的引用索引列表
    """

    def __init__(self) -> None:
        """初始化引用解析器。"""
        self._buffer: str = ""
        self._citations: list[int] = []

    def feed(self, text: str) -> list[dict[str, Any]]:
        """
        输入一段文本，返回解析出的事件列表。

        事件类型：
        - {"type": "token", "text": "..."}  普通文本
        - {"type": "citation", "index": N}   引用标记

        Args:
            text: LLM 输出的新文本片段

        Returns:
            解析出的事件列表
        """
        self._buffer += text
        events: list[dict[str, Any]] = []

        while True:
            match = CITATION_PATTERN.search(self._buffer)
            if not match:
                break

            # 引用前的内容 → token 事件
            prefix = self._buffer[:match.start()]
            if prefix:
                events.append({"type": "token", "text": prefix})

            # 引用标记 → citation 事件
            index = int(match.group(1))
            events.append({"type": "citation", "index": index})
            if index not in self._citations:
                self._citations.append(index)

            # 截断已处理的部分
            self._buffer = self._buffer[match.end():]

        return events

    def flush(self) -> list[dict[str, Any]]:
        """
        刷新缓冲区，将剩余内容作为 token 事件输出。

        应在 LLM 流结束时调用。

        Returns:
            剩余缓冲区内容的事件列表
        """
        events = []
        if self._buffer:
            events.append({"type": "token", "text": self._buffer})
            self._buffer = ""
        return events

    def get_used_citation_indices(self) -> list[int]:
        """获取 LLM 响应中实际使用的引用索引列表（排序去重）。"""
        return sorted(set(self._citations))

    def reset(self) -> None:
        """重置解析器状态（每次新的查询前调用）。"""
        self._buffer = ""
        self._citations = []
