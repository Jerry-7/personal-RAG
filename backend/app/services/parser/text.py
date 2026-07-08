# Personal RAG - 纯文本解析器
"""
纯文本文件解析器模块

支持 TXT、Markdown、CSV 等文本格式的直接读取。
"""

from pathlib import Path

from app.services.parser.base import BaseParser, ParsedDocument


class TextParser(BaseParser):
    """
    纯文本文件解析器。

    支持 .txt, .md, .csv 格式。直接读取文件内容，
    CSV 文件保留原始文本（不做结构化解析以保证 LLM 理解）。
    """

    @property
    def supported_extensions(self) -> list[str]:
        """支持常见的文本格式。"""
        return ["txt", "md", "csv", "json", "xml", "yaml", "yml", "log"]

    def parse(self, file_path: str) -> ParsedDocument:
        """
        读取文本文件内容。

        尝试 UTF-8 编码，失败时回退到 GBK（兼容中文 Windows 文件）。

        Args:
            file_path: 文本文件的本地路径

        Returns:
            ParsedDocument: 包含文件完整文本内容

        Raises:
            FileNotFoundError: 文件不存在
            UnicodeDecodeError: 无法识别文件编码
        """
        path = Path(file_path)

        # 尝试多种编码
        text = None
        for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
            try:
                text = path.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if text is None:
            raise ValueError(f"无法识别文件编码: {file_path}")

        return ParsedDocument(
            text=text,
            metadata={
                "file_size": path.stat().st_size,
                "extension": path.suffix.lower().lstrip("."),
            },
            file_type=path.suffix.lower().lstrip("."),
        )
