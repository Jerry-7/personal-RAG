# Personal RAG - 文本分块服务
"""
文本分块模块

实现递归字符分割策略，使用中文感知的分隔符列表。
将长文档切分为适合 embedding 和检索的固定大小块，
并保留重叠以保证跨块边界的语义连续性。
"""

import re
from typing import Any, Optional

from app.config import settings


class TextChunker:
    """
    递归字符文本分块器。

    采用分层分隔符策略：
    1. 首先尝试在段落边界 (\n\n) 切分
    2. 然后在换行符 (\n) 切分
    3. 接着在中文标点（。！？；）切分
    4. 再在英文标点 (.!?;) 切分
    5. 最后在空格处切分
    6. 如果都失败，则强制按字符数切分

    这种分层策略确保分块在语义上尽量完整.

    Attributes:
        chunk_size: 每个分块的目标最大字符数
        chunk_overlap: 相邻分块之间的重叠字符数
        separators: 分隔符优先级列表（中文感知）
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None:
        """
        初始化分块器。

        Args:
            chunk_size: 每个分块的目标最大字符数
            chunk_overlap: 相邻分块之间的重叠字符数
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # 中文感知的分隔符优先级
        self.separators: list[str] = [
            "\n\n",
            "\n",
            "。",
            "！",
            "？",
            "；",
            ". ",
            "! ",
            "? ",
            "; ",
            " ",
            "",
        ]

    def chunk_text(
        self,
        text: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        将文本切分为多个带元数据的分块。

        Args:
            text: 要切分的完整文本
            metadata: 附加到每个分块的基础元数据

        Returns:
            分块列表，每项包含 {text, metadata, chunk_index}
        """
        base_meta = metadata or {}
        chunks = self._split_recursive(text)
        result = []
        for i, chunk_text in enumerate(chunks):
            chunk_meta = {**base_meta, "chunk_index": i}
            # 尝试推断视频/音频分块的时间戳
            if "start_timestamp" not in chunk_meta:
                chunk_meta["start_timestamp"] = None
            if "end_timestamp" not in chunk_meta:
                chunk_meta["end_timestamp"] = None
            result.append({
                "text": chunk_text,
                "metadata": chunk_meta,
                "chunk_index": i,
            })
        return result

    def chunk_parsed_document(
        self,
        parsed_doc,  # ParsedDocument
    ) -> list[dict[str, Any]]:
        """
        将 ParsedDocument 切分为分块，保留页面级别元数据。

        对于 PDF 文档，尝试为每个分块标注来源页码。
        对于视频/音频，保留时间戳信息。

        Args:
            parsed_doc: 解析后的文档对象

        Returns:
            分块列表，每项包含 {text, metadata, chunk_index}
        """
        all_chunks = []

        # 如果有页面信息（PDF），按页创建基础元数据
        if parsed_doc.pages:
            for page_info in parsed_doc.pages:
                page_meta = {
                    **parsed_doc.metadata,
                    "page_number": page_info.get("page_num"),
                    "file_type": parsed_doc.file_type,
                    "source_type": "text",
                }
                page_chunks = self.chunk_text(
                    page_info["text"],
                    metadata=page_meta,
                )
                # 为每页的分块重新编号
                all_chunks.extend(page_chunks)

        # 如果有时间分段（视频/音频），按段创建分块
        elif parsed_doc.segments:
            for seg in parsed_doc.segments:
                seg_meta = {
                    **parsed_doc.metadata,
                    "start_timestamp": seg.get("start"),
                    "end_timestamp": seg.get("end"),
                    "file_type": parsed_doc.file_type,
                    "source_type": "video" if parsed_doc.file_type in ("mp4", "avi", "mkv", "mov") else "audio",
                }
                seg_chunks = self.chunk_text(
                    seg["text"],
                    metadata=seg_meta,
                )
                for ch in seg_chunks:
                    ch["metadata"]["start_timestamp"] = seg.get("start")
                    ch["metadata"]["end_timestamp"] = seg.get("end")
                all_chunks.extend(seg_chunks)

        # 普通文本文件
        else:
            base_meta = {
                **parsed_doc.metadata,
                "file_type": parsed_doc.file_type,
                "source_type": "text",
            }
            all_chunks = self.chunk_text(parsed_doc.text, metadata=base_meta)

        # 重新编号所有分块
        for i, ch in enumerate(all_chunks):
            ch["chunk_index"] = i
            ch["metadata"]["chunk_index"] = i

        return all_chunks

    def _split_recursive(self, text: str) -> list[str]:
        """
        递归分块的核心方法。

        按 separators 优先级顺序尝试切分文本。
        对于超出 chunk_size 的片段，递归使用下一级分隔符。

        Args:
            text: 要切分的文本

        Returns:
            切分后的文本块列表
        """
        # 文本足够短，直接返回
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        # 尝试用各级分隔符切分
        for sep in self.separators:
            if sep == "":
                # 最后手段：按字符数强制切分
                return self._force_split(text)

            splits = text.split(sep)
            # 如果分隔符没有成功切分（只有一个片段），尝试下一级
            if len(splits) == 1:
                continue

            chunks = []
            current_chunk = ""
            for split in splits:
                # 用分隔符连接（非空分隔符时）
                candidate = current_chunk + (sep if current_chunk else "") + split

                if len(candidate) <= self.chunk_size:
                    current_chunk = candidate
                else:
                    # 当前累积块已满
                    if current_chunk:
                        chunks.append(current_chunk)

                    # 如果新片段本身也超长，递归用下一级分隔符处理
                    if len(split) > self.chunk_size:
                        sub_chunks = self._split_recursive(split)
                        # 最后一个子块与后续内容合并（保留重叠）
                        if sub_chunks:
                            current_chunk = sub_chunks[-1]
                            chunks.extend(sub_chunks[:-1])
                        else:
                            current_chunk = ""
                    else:
                        current_chunk = split

            if current_chunk:
                chunks.append(current_chunk)

            # 如果切分成功，进行重叠处理
            if len(chunks) > 1:
                return self._add_overlap(chunks)

        # 所有分隔符都失败，强制切分
        return self._force_split(text)

    def _force_split(self, text: str) -> list[str]:
        """
        按固定大小强制切分文本（最后手段）。

        当所有语义分隔符都无法切分时使用（例如超长无标点连续文本）。

        Args:
            text: 要切分的文本

        Returns:
            固定大小的文本块列表
        """
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunks.append(text[start:end])
            start = end - self.chunk_overlap if end < len(text) else end
        return chunks

    def _add_overlap(self, chunks: list[str]) -> list[str]:
        """
        为分块添加重叠文本。

        将前一个分块的末尾部分附加到下一个分块的开头，
        确保跨分块边界的语境不会丢失。

        Args:
            chunks: 无重叠的分块列表

        Returns:
            带重叠的分块列表
        """
        if self.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks

        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            # 取前一个分块的末尾作为重叠
            overlap_text = prev[-self.chunk_overlap:] if len(prev) > self.chunk_overlap else prev
            # 去重：如果当前分块已经以前缀方式包含重叠文本
            if chunks[i].startswith(overlap_text[-50:]):
                result.append(chunks[i])
            else:
                result.append(overlap_text + "\n" + chunks[i])

        return result


# 默认实例
chunker = TextChunker(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
)
