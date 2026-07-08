# Personal RAG - PDF 解析器
"""
PDF 解析器模块

使用 pymupdf4llm 提取 PDF 文本内容。
支持 Markdown 格式输出、页面级分块、表格检测。
原生 UTF-8 支持中文文本提取。
"""

import fitz  # PyMuPDF
from app.services.parser.base import BaseParser, ParsedDocument


class PDFParser(BaseParser):
    """
    PDF 文件解析器。

    使用 PyMuPDF (fitz) 直接提取文本，保持页面级别的结构信息。
    pymupdf4llm 需要额外安装时才使用其 Markdown 转换功能。

    对于包含图片的 PDF 页面（如扫描件），仅提取文字层的文本；
    OCR 处理由 ImageParser 单独负责。
    """

    @property
    def supported_extensions(self) -> list[str]:
        """支持 .pdf 文件。"""
        return ["pdf"]

    def parse(self, file_path: str) -> ParsedDocument:
        """
        解析 PDF 文件，提取文本和页面元数据。

        逐页读取文本内容，保留页码信息用于后续分块和引用定位。

        Args:
            file_path: PDF 文件的本地路径

        Returns:
            ParsedDocument: 包含完整文本、每页内容和元数据
                - text: 完整文本（页间用换行分隔）
                - pages: [{page_num: int, text: str}, ...]
                - metadata: {title, author, subject, page_count}

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: PDF 文件损坏或无法读取
        """
        doc = fitz.open(file_path)
        metadata = doc.metadata or {}
        page_count = doc.page_count

        full_text_parts: list[str] = []
        pages: list[dict] = []

        for page_num in range(page_count):
            page = doc[page_num]
            page_text = page.get_text("text")
            pages.append({
                "page_num": page_num + 1,  # 1-indexed
                "text": page_text,
            })
            full_text_parts.append(page_text)

        doc.close()

        return ParsedDocument(
            text="\n\n".join(full_text_parts),
            metadata={
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "subject": metadata.get("subject", ""),
                "page_count": page_count,
            },
            pages=pages,
            file_type="pdf",
        )
