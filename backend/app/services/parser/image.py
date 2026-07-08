# Personal RAG - 图片 OCR 解析器
"""
图片 OCR 解析器模块

使用 Tesseract OCR 或 PaddleOCR 从图片中提取文字。
支持 JPG, PNG, BMP, TIFF 等常见图片格式。
对于 PDF 中的扫描页，也可通过此解析器处理。
"""

from pathlib import Path
from typing import Optional

from PIL import Image

from app.services.parser.base import BaseParser, ParsedDocument


class ImageParser(BaseParser):
    """
    图片 OCR 文本提取器。

    优先使用 PaddleOCR（中英文混合识别更好），
    回退到 Tesseract（安装更简单，英文识别好）。

    Attributes:
        engine: OCR 引擎 ("paddle" | "tesseract" | "auto")
    """

    _SUPPORTED_EXTENSIONS = [
        "jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp",
    ]

    def __init__(self, engine: str = "auto") -> None:
        """
        初始化图片解析器。

        Args:
            engine: OCR 引擎选择
                - "auto": 自动检测可用的引擎（PaddleOCR > Tesseract）
                - "paddle": 强制使用 PaddleOCR
                - "tesseract": 强制使用 Tesseract
        """
        self.engine = engine
        self._ocr = None

    @property
    def supported_extensions(self) -> list[str]:
        """返回支持的图片文件扩展名。"""
        return self._SUPPORTED_EXTENSIONS

    def parse(self, file_path: str) -> ParsedDocument:
        """
        对图片文件执行 OCR 文本提取。

        Args:
            file_path: 图片文件路径

        Returns:
            ParsedDocument:
                - text: 提取的文本
                - metadata: {width, height, engine_used}

        Raises:
            FileNotFoundError: 文件不存在
            RuntimeError: OCR 引擎不可用
        """
        img_path = Path(file_path)
        if not img_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 读取图片获取基本信息
        img = Image.open(file_path)
        width, height = img.size

        # 选择引擎并执行 OCR
        engine_used, text = self._do_ocr(file_path)

        return ParsedDocument(
            text=text,
            metadata={
                "width": width,
                "height": height,
                "engine_used": engine_used,
            },
            file_type=img_path.suffix.lower().lstrip("."),
        )

    def _do_ocr(self, file_path: str) -> tuple[str, str]:
        """
        执行 OCR 并返回使用的引擎名称和文本。

        按优先级尝试：
        1. PaddleOCR（如果是 auto 或 paddle 模式）
        2. Tesseract（如果是 auto 或 tesseract 模式）

        Args:
            file_path: 图片文件路径

        Returns:
            (engine_name, extracted_text)

        Raises:
            RuntimeError: 所有可用引擎都失败了
        """
        errors = []

        # 尝试 PaddleOCR
        if self.engine in ("auto", "paddle"):
            try:
                text = self._ocr_paddle(file_path)
                if text.strip():
                    return ("paddleocr", text)
            except ImportError as e:
                errors.append(f"PaddleOCR: {e}")
            except Exception as e:
                errors.append(f"PaddleOCR: {e}")

        # 尝试 Tesseract
        if self.engine in ("auto", "tesseract"):
            try:
                text = self._ocr_tesseract(file_path)
                return ("tesseract", text)
            except ImportError as e:
                errors.append(f"Tesseract: {e}")
            except Exception as e:
                errors.append(f"Tesseract: {e}")

        raise RuntimeError(
            f"所有 OCR 引擎均不可用。\n"
            f"错误详情:\n" + "\n".join(f"  - {e}" for e in errors) + "\n"
            f"请安装其中一个:\n"
            f"  Tesseract: https://github.com/UB-Mannheim/tesseract/wiki\n"
            f"  PaddleOCR: pip install paddlepaddle paddleocr"
        )

    @staticmethod
    def _ocr_tesseract(file_path: str) -> str:
        """
        使用 Tesseract OCR 提取文字。

        Tesseract 对英文识别很好，中文需要额外下载语言包。
        在 Windows 上需要手动安装 Tesseract 并加入 PATH。
        """
        try:
            import pytesseract
        except ImportError:
            raise ImportError(
                "pytesseract 未安装。运行: pip install pytesseract"
            )

        # 尝试中英文混合识别
        try:
            text = pytesseract.image_to_string(
                Image.open(file_path),
                lang="chi_sim+eng",
            )
        except Exception:
            # 回退到仅英文
            text = pytesseract.image_to_string(
                Image.open(file_path),
                lang="eng",
            )

        return text.strip()

    @staticmethod
    def _ocr_paddle(file_path: str) -> str:
        """
        使用 PaddleOCR 提取文字。

        PaddleOCR 对中英文混合识别效果最好（95%+ 中文准确率），
        但依赖 PaddlePaddle（~500MB）。
        """
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            raise ImportError(
                "PaddleOCR 未安装。运行:\n"
                "  pip install paddlepaddle paddleocr"
            )

        # PaddleOCR 单例避免重复初始化
        if not hasattr(ImageParser, "_paddle_instance"):
            ImageParser._paddle_instance = PaddleOCR(
                use_angle_cls=True,  # 文字方向分类
                lang="ch",           # 中英文混合
                show_log=False,
            )

        ocr = ImageParser._paddle_instance
        result = ocr.ocr(file_path, cls=True)

        if not result or not result[0]:
            return ""

        # 拼接识别结果
        lines = []
        for line_data in result[0]:
            if line_data and len(line_data) >= 2:
                text = line_data[1][0]  # (box, (text, confidence))
                if text:
                    lines.append(text)

        return "\n".join(lines)
