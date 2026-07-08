# Personal RAG - 文件工具函数
"""
文件工具模块

提供 MIME 类型检测、文件哈希计算、安全文件名生成等辅助功能。
"""

import hashlib
from pathlib import Path


def compute_file_hash(file_path: str, algorithm: str = "sha256") -> str:
    """
    计算文件的哈希值（用于去重）。

    读取文件块以避免大文件占用过多内存。

    Args:
        file_path: 文件路径
        algorithm: 哈希算法 (sha256, md5 等)

    Returns:
        十六进制哈希字符串
    """
    h = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def detect_mime_type(file_path: str) -> str:
    """
    检测文件的 MIME 类型。

    使用 python-magic-bin 进行准确的 MIME 检测（非扩展名猜测）。

    Args:
        file_path: 文件路径

    Returns:
        MIME 类型字符串，如 "application/pdf", "text/plain"
        如果 magic 库不可用，则回退到扩展名检测
    """
    try:
        import magic
        return magic.from_file(file_path, mime=True)
    except ImportError:
        # 回退: 基于扩展名的简单映射
        return _guess_mime_by_extension(file_path)


def _guess_mime_by_extension(file_path: str) -> str:
    """基于文件扩展名的 MIME 类型猜测（回退方案）。"""
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".wav": "audio/wav",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
    }
    return mapping.get(ext, "application/octet-stream")


def get_safe_filename(original_name: str, file_hash: str) -> str:
    """
    生成安全的存储文件名（哈希前缀 + 原始名）。

    防止路径遍历攻击和文件名冲突。

    Args:
        original_name: 原始文件名
        file_hash: 文件哈希值

    Returns:
        安全的文件名
    """
    # 移除路径分隔符
    safe_name = Path(original_name).name
    return f"{file_hash[:16]}_{safe_name}"
