"""Personal RAG - 文本工具"""

from __future__ import annotations


def clip_to_sentence(text: str, limit: int) -> str:
    """在句子边界截断文本, 避免从半句/单词中间切断。

    若 limit 内找不到句边界, 退化为普通截断以保证不超长。
    """
    if limit < 1:
        return ""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for boundary in ("。", "！", "？", "；", ". ", "! ", "? ", ".\n", "\n"):
        index = cut.rfind(boundary)
        if index >= 0:
            return cut[: index + len(boundary)].rstrip()
    return cut.rstrip()
