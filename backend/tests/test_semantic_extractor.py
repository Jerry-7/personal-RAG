"""SemanticExtractor / clip_to_sentence / page_evidence 缓存测试."""

import unittest
from unittest.mock import patch

from app.agent.context import AgentRunContext
from app.config import settings
from app.providers.base import LLMResponse
from app.services.context_compression import CompressionStats
from app.services.semantic_extractor import (
    SemanticExtraction,
    SemanticExtractor,
)
from app.services.text_utils import clip_to_sentence
from app.services.web_fetcher import FetchedPage
from app.services.web_research import WebResearchService


class _RaisingProvider:
    """任何模型调用都失败, 用于触发兜底路径."""

    async def chat(self, *, messages, **kwargs):
        raise RuntimeError("provider down")


class _TwoPhaseProvider:
    """第一阶段返回语义提取结果, 压缩阶段返回短文本 (均不发真实请求)."""

    def __init__(self, extraction_text: str, compressed_text: str) -> None:
        self.calls = 0
        self.last_system = ""
        self.extraction_text = extraction_text
        self.compressed_text = compressed_text

    async def chat(self, *, messages, **kwargs):
        self.calls += 1
        self.last_system = messages[0]["content"]
        if "target-focused evidence extraction Agent" in self.last_system:
            return LLMResponse(content=self.extraction_text)
        return LLMResponse(content=self.compressed_text)


class SemanticExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_content_returns_without_any_provider_call(self):
        content = "简短的研究内容。"
        extractor = SemanticExtractor(provider=_RaisingProvider())  # type: ignore[arg-type]

        result = await extractor.extract(content, objective="目标")

        self.assertEqual(result.decision, "short_circuit")
        self.assertEqual(result.content, content)
        self.assertEqual(result.stats.calls, 0)

    async def test_large_content_short_circuits_when_disabled(self):
        extractor = SemanticExtractor(
            provider=_RaisingProvider(),  # type: ignore[arg-type]
            enabled=False,
        )
        content = "背景数据。" * 3000

        result = await extractor.extract(content, objective="目标")

        self.assertEqual(result.decision, "short_circuit")
        self.assertEqual(result.content, content)

    async def test_blank_content_or_objective_short_circuits(self):
        extractor = SemanticExtractor(provider=_RaisingProvider())  # type: ignore[arg-type]
        self.assertEqual(
            (await extractor.extract("   ", objective="目标")).decision,
            "short_circuit",
        )
        self.assertEqual(
            (await extractor.extract("正文内容。", objective="  ")).decision,
            "short_circuit",
        )

    async def test_extraction_agent_reduces_within_budget(self):
        provider = _TwoPhaseProvider("提取出的核心证据内容。", "压缩后内容。")
        extractor = SemanticExtractor(provider=provider)  # type: ignore[arg-type]
        content = "历史背景。" * 200  # 远超预算

        result = await extractor.extract(content, objective="核心证据", target_chars=64)

        self.assertEqual(result.decision, "extracted")
        self.assertEqual(result.content, "提取出的核心证据内容。")
        self.assertEqual(result.stats.calls, 1)
        # 提取 prompt 携带字符预算
        self.assertIn("within 64 characters", provider.last_system)

    async def test_over_budget_extraction_is_compressed_by_agent(self):
        provider = _TwoPhaseProvider(
            extraction_text="证据细节。" * 60,  # 仍超预算
            compressed_text="压缩后的摘要证据。",
        )
        extractor = SemanticExtractor(provider=provider)  # type: ignore[arg-type]
        content = "历史背景。" * 200

        result = await extractor.extract(content, objective="证据", target_chars=64)

        self.assertEqual(result.decision, "compressed")
        self.assertEqual(result.content, "压缩后的摘要证据。")
        self.assertGreaterEqual(result.stats.calls, 2)

    async def test_provider_failure_keeps_whole_keyword_paragraphs(self):
        extractor = SemanticExtractor(provider=_RaisingProvider())  # type: ignore[arg-type]
        keyword_para = "本段包含目标关键词相关的技术细节讨论内容。"
        content = "\n\n".join([
            "与目标无关的历史背景填充。" * 12,  # 超预算, 整段跳过
            keyword_para,
            "其他无关说明文字填充。" * 12,  # 超预算, 整段跳过
        ])

        result = await extractor.extract(content, objective="目标关键词", target_chars=100)

        self.assertEqual(result.decision, "keyword_fallback")
        self.assertEqual(result.content, keyword_para)

    async def test_all_paragraphs_over_budget_clips_at_sentence_boundary(self):
        extractor = SemanticExtractor(provider=_RaisingProvider())  # type: ignore[arg-type]
        content = "第一句。第二句。" + "补充细节。" * 60  # 单个巨型段落

        result = await extractor.extract(content, objective="细节", target_chars=50)

        self.assertEqual(result.decision, "keyword_fallback")
        self.assertLessEqual(len(result.content), 50)
        self.assertTrue(result.content.endswith("。"))

    async def test_default_model_pins_fast_tier(self):
        with patch.object(settings, "agent_fast_model", "fast-extract-model"):
            extractor = SemanticExtractor(provider=_RaisingProvider())  # type: ignore[arg-type]
        self.assertEqual(extractor.model_name, "fast-extract-model")

    async def test_default_model_falls_back_to_llm_default_when_fast_unset(self):
        with patch.object(settings, "agent_fast_model", None), patch.object(
            settings, "ollama_llm_model", "default-llm"
        ):
            extractor = SemanticExtractor(provider=_RaisingProvider())  # type: ignore[arg-type]
        self.assertEqual(extractor.model_name, "default-llm")

    async def test_web_evidence_extraction_caches_per_page_url(self):
        service = WebResearchService()
        page = FetchedPage(
            "https://example.com/x", "T", "正文", "text/html", 200, "hash", []
        )
        context = AgentRunContext(db=None, conversation_id="conv")
        extract_calls: list[str] = []

        class FakeExtractor:
            async def extract(
                self, content, *, objective, target_chars=None, purpose="web page evidence"
            ):
                extract_calls.append(content)
                return SemanticExtraction(
                    "证据内容", "extracted", CompressionStats(1, 1, calls=1)
                )

        with patch(
            "app.services.semantic_extractor.semantic_extractor", FakeExtractor()
        ):
            first = await service._extract_evidence(context, page, "目标")
            second = await service._extract_evidence(context, page, "目标")

        self.assertEqual(first, second)
        self.assertEqual(first, "证据内容")
        self.assertEqual(len(extract_calls), 1)  # 同一 URL 只提取一次
        self.assertEqual(context.page_evidence, {"https://example.com/x": "证据内容"})


class ClipToSentenceTests(unittest.TestCase):
    def test_cuts_at_cjk_sentence_boundary(self):
        self.assertEqual(clip_to_sentence("第一句。第二句内容。", 8), "第一句。")

    def test_cuts_at_latin_period(self):
        self.assertEqual(clip_to_sentence("First sentence. Second one here.", 16), "First sentence.")

    def test_falls_back_to_plain_cut_when_no_boundary(self):
        cut = clip_to_sentence("abcdefghij", 4)
        self.assertEqual(cut, "abcd")

    def test_returns_whole_text_when_within_limit(self):
        text = "整段都很短。"
        self.assertEqual(clip_to_sentence(text, 100), text)

    def test_empty_and_invalid_limits(self):
        self.assertEqual(clip_to_sentence("", 100), "")
        self.assertEqual(clip_to_sentence("text", 0), "")
        self.assertEqual(clip_to_sentence(None, 10), "")  # type: ignore[arg-type]

    def test_preview_uses_sentence_clip(self):
        preview = WebResearchService._preview("第一句。第二句很长内容继续。", 8)
        self.assertEqual(preview, "第一句。")


if __name__ == "__main__":
    unittest.main()
