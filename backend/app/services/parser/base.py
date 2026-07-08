# Personal RAG - 文档解析器抽象基类
"""
解析器抽象基类模块

定义 BaseParser 抽象类和 ParsedDocument 数据类。
所有文件格式解析器（PDF, DOCX, TXT, 视频等）都继承 BaseParser，
实现统一的 parse() 接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ParsedDocument:
    """
    解析后的文档数据结构。

    包含从原始文件中提取的纯文本和丰富的元数据。
    对于多页文档，pages 列表存储每页内容和页码。
    对于视频/音频，segments 列表存储带时间戳的文本段。

    Attributes:
        text: 文档完整纯文本
        metadata: 文档级别元数据（标题、作者等）
        pages: 按页/段分割的内容列表
        file_type: 原始文件类型
    """
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    pages: list[dict[str, Any]] = field(default_factory=list)  # [{page_num, text}, ...]
    segments: list[dict[str, Any]] = field(default_factory=list)  # [{start, end, text}, ...]
    file_type: str = ""


class BaseParser(ABC):
    """
    文档解析器抽象基类。

    所有格式特定的解析器必须实现此接口。
    parse() 方法接收文件路径，返回包含提取文本和元数据的 ParsedDocument。
    """

    @abstractmethod
    def parse(self, file_path: str) -> ParsedDocument:
        """
        解析文件并提取文本和元数据。

        Args:
            file_path: 待解析文件的本地路径

        Returns:
            ParsedDocument 包含提取的文本和元数据

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持或损坏
        """
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """返回此解析器支持的文件扩展名列表（不含点号前缀，如 ['pdf', 'docx']）。"""
        ...
