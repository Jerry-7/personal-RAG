# Personal RAG - 解析器注册表
"""
解析器注册表模块

维护文件扩展名到解析器类的映射。当新文件上传时，
通过扩展名匹配合适的解析器进行文本提取。
支持运行时注册新解析器。
"""

from typing import Optional, Type

from app.services.parser.base import BaseParser


class ParserRegistry:
    """
    解析器注册表（单例模式）。

    根据文件扩展名查找合适的解析器。
    使用注册模式，方便后续添加新的文件格式支持。

    Usage:
        registry = ParserRegistry()
        registry.register(PDFParser)
        parser = registry.get_parser("pdf")
        result = parser.parse("/path/to/file.pdf")
    """

    def __init__(self) -> None:
        """初始化空的解析器注册表。"""
        self._parsers: dict[str, BaseParser] = {}

    def register(self, parser: BaseParser) -> None:
        """
        注册一个解析器实例。

        将解析器声明的所有扩展名映射到此解析器。

        Args:
            parser: 要注册的解析器实例

        Raises:
            ValueError: 如果扩展名已被其他解析器注册
        """
        for ext in parser.supported_extensions:
            ext_lower = ext.lower().lstrip(".")
            if ext_lower in self._parsers:
                # 不抛出异常 - 后续注册覆盖前者（用于自定义解析器）
                pass
            self._parsers[ext_lower] = parser

    def get_parser(self, extension: str) -> Optional[BaseParser]:
        """
        根据文件扩展名获取对应的解析器。

        Args:
            extension: 文件扩展名（可含或不含点号前缀，如 "pdf" 或 ".pdf"）

        Returns:
            匹配的解析器实例，未注册的扩展名返回 None
        """
        ext = extension.lower().lstrip(".")
        return self._parsers.get(ext)

    def is_supported(self, extension: str) -> bool:
        """
        检查给定的文件扩展名是否有对应的解析器。

        Args:
            extension: 文件扩展名

        Returns:
            True 表示存在可用解析器
        """
        return self.get_parser(extension) is not None

    @property
    def supported_extensions(self) -> list[str]:
        """返回所有已注册的文件扩展名列表。"""
        return list(self._parsers.keys())


# 全局单例
parser_registry = ParserRegistry()
